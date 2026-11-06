"""ManagedRun command names, help, and roles shared by the CLI and capabilities."""

from types import MappingProxyType
from typing import Literal, NamedTuple


CommandRole = Literal["lifecycle", "host_runner", "recovery"]


class ManagedRunCommand(NamedTuple):
    role: CommandRole
    help: str
    requires_ports: bool = False


# In public CLI help order. The host runs the runner commands on the user's behalf.
MANAGED_RUN_COMMANDS = MappingProxyType({
    "start": ManagedRunCommand("lifecycle", "Start a durable managed run from one confirmed authorization window.", requires_ports=True),
    "tick": ManagedRunCommand("host_runner", "Advance the current managed run by one bounded cycle.", requires_ports=True),
    "run": ManagedRunCommand("host_runner", "Advance to a wait point, or keep polling the same run with --wait.", requires_ports=True),
    "status": ManagedRunCommand("lifecycle", "Show the current managed run."),
    "pause": ManagedRunCommand("lifecycle", "Pause before the next managed mutation."),
    "resume": ManagedRunCommand("lifecycle", "Resume the same durable managed run."),
    "reconcile": ManagedRunCommand("recovery", "Reobserve an unknown send without sending again.", requires_ports=True),
    "stop": ManagedRunCommand("lifecycle", "Stop the current managed run."),
})


def command_names_for_role(role: CommandRole) -> list[str]:
    names = [name for name, command in MANAGED_RUN_COMMANDS.items() if command.role == role]
    # The capability contract lists run before tick, while CLI help lists tick first.
    return sorted(names) if role == "host_runner" else names
