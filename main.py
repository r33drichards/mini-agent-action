import re
from dataclasses import dataclass
from typing import Optional
from minisweagent.agents.default import (
    DefaultAgent, NonTerminatingException, AgentConfig, Submitted
)
import subprocess


@dataclass
class ValidatingAgentConfig(AgentConfig):
    exec_command: Optional[str] = None
    
    
class ValidatingAgent(DefaultAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, config_class=ValidatingAgentConfig)

    def execute_action(self, action: dict) -> dict:
        if action["action"] == "submit":
            # validate the command succeeded by checking the exit code
            if self.config.exec_command:
                result = subprocess.run(
                    self.config.exec_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise NonTerminatingException(
                        "validation failed\nSTDOUT:\n" + (result.stdout or "") + "\nSTDERR:\n" + (result.stderr or "")
                    )
            raise Submitted("The agent has finished its task.")
        return super().execute_action(action)
      
    def has_finished(self, output: dict[str, str]):
        """Raises Submitted exception with final output if the agent has finished its task."""
        if self.config.exec_command:
            result = subprocess.run(
                self.config.exec_command,
                shell=True,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise NonTerminatingException(
                    "validation failed\nSTDOUT:\n" + (result.stdout or "") + "\nSTDERR:\n" + (result.stderr or "")
                )
        raise Submitted("The agent has finished its task.")
    
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    # Support optional 'run' subcommand like: `python main.py run --exec ...`
    parser.add_argument("command", nargs="?", default="run")
    parser.add_argument("--task", type=str, required=True)
    parser.add_argument("--exec", type=str, required=True)
    args = parser.parse_args()
    agent = ValidatingAgent(
        exec_command=args.exec

    )
    agent.run(args.task)
