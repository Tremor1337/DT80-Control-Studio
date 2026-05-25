from dataclasses import dataclass

@dataclass(frozen=True)
class CommandInfo:
    name: str
    description: str
    example: str

# A practical starter catalog (we’ll expand it)
COMMANDS: dict[str, CommandInfo] = {
    "STATUS": CommandInfo("STATUS", "Show device status report.", "STATUS"),
    "TEST": CommandInfo("TEST", "Show test report.", "TEST"),
    "DIRJOBS": CommandInfo("DIRJOBS", "List stored job names.", "DIRJOBS"),
    "CURJOB": CommandInfo("CURJOB", "Show current active job name.", "CURJOB"),
    "SHOWPROG": CommandInfo("SHOWPROG", "Print stored job program text.", 'SHOWPROG"Boiler01"'),
    "RUNJOB": CommandInfo("RUNJOB", "Load and activate a stored job.", 'RUNJOB "Boiler01"'),
    "LOGON": CommandInfo("LOGON", "Enable data logging.", "LOGON"),
    "LOGOFF": CommandInfo("LOGOFF", "Disable data logging.", "LOGOFF"),
    "LISTD": CommandInfo("LISTD", "List logged data/alarm stores.", "LISTD"),
    "COPYD": CommandInfo("COPYD", "Unload/export logged data.", "COPYD"),
    "DELD": CommandInfo("DELD", "Delete logged data from stores.", "DELD"),
    "DIR": CommandInfo("DIR", "List directory (default B:\\).", "DIR B:\\"),
    "TYPE": CommandInfo("TYPE", "Show contents of a text file.", "TYPE B:\\JOBS\\Boiler01\\PROGRAM.DXC"),
}
