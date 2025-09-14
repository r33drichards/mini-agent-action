from dataclasses import dataclass
from typing import Optional
from minisweagent.agents.default import (
    DefaultAgent,
    NonTerminatingException,
    AgentConfig,
    Submitted,
)
import subprocess
from minisweagent.models import get_model
from minisweagent.environments.local import LocalEnvironment


debug = False


@dataclass
class ValidatingAgentConfig(AgentConfig):
    exec_command: Optional[str] = None


class ValidatingAgent(DefaultAgent):
    def __init__(self, *args, model_name: str, **kwargs):
        super().__init__(
            *args,
            **kwargs,
            config_class=ValidatingAgentConfig,
            model=get_model(input_model_name=model_name),
            env=LocalEnvironment(),
        )

    # More informative logging of the agent's message log when --debug is set
    def add_message(self, role: str, content: str, **kwargs):
        super().add_message(role, content, **kwargs)
        if debug:
            assistant_steps = sum(1 for m in self.messages if m.get("role") == "assistant")
            tag = f"step {assistant_steps:02d}" if role in ("assistant", "user") else "setup"
            cost_str = ""
            try:
                if role == "assistant":
                    cost_val = getattr(self.model, "cost", 0.0)
                    n_calls_val = getattr(self.model, "n_calls", 0)
                    cost_str = f" (calls={n_calls_val}, cost={cost_val:.4f})"
            except Exception:
                pass
            print(f"[{tag}] {role}{cost_str}:")
            print(content if isinstance(content, str) else str(content))
            print()

    def _summarize_for_log(self, text: str, limit: int = 800) -> str:
        if not isinstance(text, str):
            return str(text)
        t = text.rstrip()
        if len(t) <= limit:
            return t
        return t[:limit] + f"\n... [truncated {len(t) - limit} chars]"

    def has_finished(self, output: dict[str, str]):
        """Only validate when the agent signals completion via sentinel line."""
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if not lines:
            return
        first_line = lines[0].strip()
        if first_line not in [
            "MINI_SWE_AGENT_FINAL_OUTPUT",
            "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]:
            # Not a completion signal; continue stepping without validation
            return

        # Agent signaled completion; run validation if configured
        if self.config.exec_command:
            result = subprocess.run(
                self.config.exec_command,
                shell=True,
                capture_output=True,
                text=True,
            )
            if debug:
                print(f"validation result: {result.stdout}{result.stderr}")
            if result.returncode != 0:
                raise NonTerminatingException(
                    "validation failed\nSTDOUT:\n"
                    + (result.stdout or "")
                    + "\nSTDERR:\n"
                    + (result.stderr or "")
                )

        # Validation passed (or not configured) — submit final output (everything after the sentinel)
        raise Submitted("".join(lines[1:]))


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, required=True)
    parser.add_argument("--exec", type=str, required=True)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514")
    args = parser.parse_args()
    agent = ValidatingAgent(exec_command=args.exec, model_name=args.model)
    global debug
    debug = args.debug
    status, message = agent.run(args.task)
    if debug:
        try:
            cost_val = getattr(agent.model, "cost", 0.0)
            n_calls_val = getattr(agent.model, "n_calls", 0)
            print(f"finished with status={status}, steps={n_calls_val}, cost={cost_val:.4f}")
        except Exception:
            print(f"finished with status={status}")
        # Show the full transcript
        if agent.messages:
            print("full transcript:")
            for idx, m in enumerate(agent.messages, start=1):
                role = m.get("role", "?")
                content = m.get("content", "")
                if not isinstance(content, str):
                    content = str(content)
                print(f"----- message {idx} ({role}) -----")
                print(content)
                print("----- end message -----\n")


if __name__ == "__main__":
    main()
