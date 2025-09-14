from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from minisweagent.agents.default import (
    DefaultAgent, NonTerminatingException, AgentConfig, Submitted
)
import subprocess
from minisweagent.models import get_model
from minisweagent.environments.local import LocalEnvironment
import os
import tempfile
import shutil
import re
import json
from datetime import datetime
from urllib import request, error, parse





debug = False

@dataclass
class ValidatingAgentConfig(AgentConfig):
    exec_command: Optional[str] = None
    
    
class ValidatingAgent(DefaultAgent):
    def __init__(self, *args, model_name: str, **kwargs):
        super().__init__(*args, **kwargs, 
                         config_class=ValidatingAgentConfig,
                         model=get_model(input_model_name=model_name),
                         env=LocalEnvironment())

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
                if debug:
                    print(f"validation result: {result.stdout} {result.stderr}")
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
            if debug:
                print(f"validation result: {result.stdout} {result.stderr}")
            if result.returncode != 0:
                raise NonTerminatingException(
                    "validation failed\nSTDOUT:\n" + (result.stdout or "") + "\nSTDERR:\n" + (result.stderr or "")
                )
        raise Submitted("The agent has finished its task.")
 
 
def _run_git(command_args: list[str], cwd: Optional[str] = None, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a git command and return the completed process. Raises if non-zero exit."""
    if debug:
        print(f"[git] cwd={cwd} args={' '.join(command_args)}")
    completed = subprocess.run(
        ["git", *command_args],
        cwd=cwd,
        capture_output=capture,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        raise RuntimeError(f"git {' '.join(command_args)} failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
    return completed


def _normalize_repo_and_urls(repo: str, token: str) -> Tuple[str, str, str, str]:
    """
    Returns (clone_url_with_token, clone_url_plain, owner, name) supporting inputs like:
    - owner/name
    - https://github.com/owner/name.git
    - git@github.com:owner/name.git
    """
    repo_str = repo.strip()
    owner: str
    name: str
    # Extract owner/name
    m = re.search(r"[:/]{1}([^/]+)/([^/]+?)(?:\\.git)?$", repo_str)
    if m:
        owner = m.group(1)
        name = m.group(2)
    else:
        # Assume bare form "owner/name"
        if "/" in repo_str:
            owner, name = repo_str.split("/", 1)
        else:
            raise ValueError("Unable to parse repository identifier. Use 'owner/name' or a Git URL.")

    # Build plain https URL
    plain_url = f"https://github.com/{owner}/{name}.git"
    # Build token URL
    safe_token = parse.quote(token, safe="")
    token_url = f"https://x-access-token:{safe_token}@github.com/{owner}/{name}.git"
    return token_url, plain_url, owner, name


def _detect_default_branch(repo_dir: str, fallback: str = "main") -> str:
    try:
        result = _run_git(["remote", "show", "origin"], cwd=repo_dir, capture=True)
        stdout = result.stdout or ""
        for line in stdout.splitlines():
            line = line.strip()
            if line.lower().startswith("head branch:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return fallback


def _http_post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTPError {e.code} for {url}: {body}")


def _create_github_pr(owner: str, name: str, token: str, head_branch: str, base_branch: str, title: str, body: str) -> Dict[str, Any]:
    api_url = f"https://api.github.com/repos/{owner}/{name}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {token}",
    }
    payload = {"title": title, "head": head_branch, "base": base_branch, "body": body}
    return _http_post_json(api_url, payload, headers=headers)


class _GitRepoContext:
    def __init__(
        self,
        repo: str,
        token: str,
        commit: Optional[str] = None,
        base_branch: str = "main",
        branch_prefix: str = "mini-agent-action",
        branch_name: Optional[str] = None,
        pr_title: Optional[str] = None,
        pr_body: Optional[str] = None,
        webhook_url: Optional[str] = None,
        cleanup: bool = True,
    ):
        self.repo_input = repo
        self.token = token
        self.commit = commit
        self.base_branch = base_branch
        self.branch_prefix = branch_prefix
        self.branch_name = branch_name
        self.pr_title = pr_title
        self.pr_body = pr_body
        self.webhook_url = webhook_url
        self.cleanup = cleanup

        self._workdir: Optional[str] = None
        self._repo_dir: Optional[str] = None
        self._prev_cwd: Optional[str] = None
        self._owner: Optional[str] = None
        self._name: Optional[str] = None
        self._plain_url: Optional[str] = None
        self._token_url: Optional[str] = None

    def __enter__(self):
        if not self.token:
            raise ValueError("Token is required to operate on the repository.")
        token_url, plain_url, owner, name = _normalize_repo_and_urls(self.repo_input, self.token)
        self._token_url = token_url
        self._plain_url = plain_url
        self._owner = owner
        self._name = name

        self._workdir = tempfile.mkdtemp(prefix="mini-agent-action-")
        self._repo_dir = os.path.join(self._workdir, name)

        # Clone using token for authentication (shallow clone)
        _run_git(["clone", "--depth", "1", "--no-tags", token_url, self._repo_dir])

        # Reset remote to plain URL (avoid storing token locally)
        _run_git(["remote", "set-url", "origin", plain_url], cwd=self._repo_dir)

        # Determine default branch if not provided
        default_branch = _detect_default_branch(self._repo_dir, fallback=self.base_branch)

        # Checkout starting point
        if self.commit:
            # Shallow fetch the specific commit/ref and check it out
            _run_git(["fetch", "--depth", "1", "origin", self.commit], cwd=self._repo_dir)
            _run_git(["checkout", self.commit], cwd=self._repo_dir)
        else:
            _run_git(["checkout", default_branch], cwd=self._repo_dir)

        # Create working branch
        if not self.branch_name:
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            self.branch_name = f"{self.branch_prefix}/{timestamp}"
        _run_git(["checkout", "-b", self.branch_name], cwd=self._repo_dir)

        # Switch CWD to repo
        self._prev_cwd = os.getcwd()
        os.chdir(self._repo_dir)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Return to original CWD ASAP
        try:
            if self._prev_cwd:
                os.chdir(self._prev_cwd)
        except Exception:
            pass

        success = exc_type is None
        pr_info: Dict[str, Any] = {}
        error_info: Optional[str] = None

        try:
            if success and self._repo_dir and self._owner and self._name and self._plain_url and self._token_url:
                # Check for changes
                status = _run_git(["status", "--porcelain"], cwd=self._repo_dir, capture=True).stdout or ""
                if status.strip():
                    # Commit and push
                    _run_git(["config", "user.email", "automation@mini-agent-action.local"], cwd=self._repo_dir)
                    _run_git(["config", "user.name", "mini-agent-action"], cwd=self._repo_dir)
                    _run_git(["add", "-A"], cwd=self._repo_dir)
                    commit_message = self.pr_title or "Automated changes by mini-agent-action"
                    _run_git(["commit", "-m", commit_message], cwd=self._repo_dir)

                    # Temporarily set token remote and push
                    _run_git(["remote", "set-url", "origin", self._token_url], cwd=self._repo_dir)
                    _run_git(["push", "-u", "origin", self.branch_name], cwd=self._repo_dir)
                    # Restore plain remote
                    _run_git(["remote", "set-url", "origin", self._plain_url], cwd=self._repo_dir)

                    # Create PR
                    base_branch = self.base_branch or _detect_default_branch(self._repo_dir)
                    title = self.pr_title or "Automated changes by mini-agent-action"
                    body = self.pr_body or "This PR was created automatically after a successful agent run."
                    pr_info = _create_github_pr(
                        self._owner, self._name, self.token, self.branch_name, base_branch, title, body
                    )
                else:
                    pr_info = {"skipped": True, "reason": "no_changes"}
        except Exception as e:
            error_info = str(e)
            success = False

        # Send webhook if configured
        try:
            if self.webhook_url:
                payload = {
                    "status": "success" if success else "failure",
                    "repo": f"{self._owner}/{self._name}" if self._owner and self._name else self.repo_input,
                    "branch": self.branch_name,
                    "pr": pr_info,
                }
                if not success:
                    payload["error"] = error_info or (str(exc_val) if exc_val else "unknown error")
                _http_post_json(self.webhook_url, payload)
        except Exception:
            # Do not mask underlying errors due to webhook failures
            pass

        # Cleanup
        try:
            if self.cleanup and self._workdir and os.path.isdir(self._workdir):
                shutil.rmtree(self._workdir, ignore_errors=True)
        except Exception:
            pass

        # Propagate original exception if any
        return False


def git_repo_context(
    repo: str,
    token: str,
    commit: Optional[str] = None,
    *,
    base_branch: str = "main",
    branch_prefix: str = "mini-agent-action",
    branch_name: Optional[str] = None,
    pr_title: Optional[str] = None,
    pr_body: Optional[str] = None,
    webhook_url: Optional[str] = None,
    cleanup: bool = True,
):
    """Convenience wrapper to create the git repo context manager."""
    return _GitRepoContext(
        repo=repo,
        token=token,
        commit=commit,
        base_branch=base_branch,
        branch_prefix=branch_prefix,
        branch_name=branch_name,
        pr_title=pr_title,
        pr_body=pr_body,
        webhook_url=webhook_url,
        cleanup=cleanup,
    )


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, required=True)
    parser.add_argument("--exec", type=str, required=True)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--model", type=str,  default="claude-sonnet-4-20250514")
    # Git/PR/Webhook integration
    parser.add_argument("--repo", type=str, help="GitHub repository (owner/name or URL)")
    parser.add_argument("--token", type=str, help="GitHub token for clone/push/API")
    parser.add_argument("--commit", type=str, help="Commit SHA or ref to check out")
    parser.add_argument("--base-branch", type=str, default="main", help="PR base branch")
    parser.add_argument("--branch-prefix", type=str, default="mini-agent-action", help="Prefix for new branch")
    parser.add_argument("--branch-name", type=str, help="Optional explicit branch name")
    parser.add_argument("--pr-title", type=str, help="Title for the pull request")
    parser.add_argument("--pr-body", type=str, help="Body for the pull request")
    parser.add_argument("--webhook-url", type=str, help="Webhook URL for status notifications")
    args = parser.parse_args()
    agent = ValidatingAgent(
        exec_command=args.exec,
        model_name=args.model
    )
    global debug
    debug = args.debug
    if args.repo:
        if not args.token:
            raise SystemExit("--token is required when --repo is provided")
        with git_repo_context(
            repo=args.repo,
            token=args.token,
            commit=args.commit,
            base_branch=args.base_branch,
            branch_prefix=args.branch_prefix,
            branch_name=args.branch_name,
            pr_title=args.pr_title,
            pr_body=args.pr_body,
            webhook_url=args.webhook_url,
        ):
            agent.run(args.task)
    else:
        agent.run(args.task)


if __name__ == "__main__":
    main()
