import os
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from filelock import FileLock

# ------------------------------------------------------------------
# Paths & Directories
# ------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT_DIR / "Outputs"
BITS_DIR = OUTPUTS_DIR / "Bits"
PROCESSED_DIR = BITS_DIR / "Processed"
ITINERARIES_DIR = OUTPUTS_DIR / "Itineraries"  # NEW: For TINNYBOT's Tour Packets
MASTER_CSV = OUTPUTS_DIR / "master-output.csv"
MASTER_CSV_LOCK = OUTPUTS_DIR / "master-output.csv.lock"
STATE_FILE = OUTPUTS_DIR / "bot_state.json"
BACKUPS_DIR = OUTPUTS_DIR / "Backups"
LOGS_DIR = ROOT_DIR / "Logs"
CONTRACTS_DIR = ROOT_DIR / "Contracts" / "Incoming"
COMPLETE_DIR = ROOT_DIR / "Contracts" / "Complete"

# Ensure directories exist
for d in [PROCESSED_DIR, BACKUPS_DIR, LOGS_DIR, CONTRACTS_DIR, COMPLETE_DIR, OUTPUTS_DIR, BITS_DIR, ITINERARIES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Schema & Headers
# ------------------------------------------------------------------

class ContractData(BaseModel):
    """Pydantic model to strictly enforce the output schema and defaults."""
    model_config = ConfigDict(populate_by_name=True)

    starting_date: str = Field(default="", alias="Starting Date")
    ending_date: str = Field(default="", alias="Ending Date")
    venue: str = Field(default="", alias="Venue")
    location: str = Field(default="", alias="Location")
    booking: str = Field(default="FALSE", alias="Booking")
    mgmt: str = Field(default="FALSE", alias="MGMT")
    door_deal: str = Field(default="FALSE", alias="Door Deal")
    dd_notes: str = Field(default="", alias="DD Notes")
    hospitality: str = Field(default="", alias="Hospitality")
    contact_name: str = Field(default="", alias="Contact Name")
    contact_details: str = Field(default="", alias="Contact Details")
    other_details: str = Field(default="", alias="Other Details")
    address: str = Field(default="", alias="Address")
    accommodations: str = Field(default="", alias="Accomodations")
    accom_address: str = Field(default="", alias="Accom Address")
    est_mileage: str = Field(default="", alias="Est. Mileage")
    time: str = Field(default="", alias="Time")
    doors: str = Field(default="", alias="Doors")
    load_in: str = Field(default="", alias="Load In")
    pay: str = Field(default="", alias="Pay")
    sound_person: str = Field(default="", alias="Sound - Person")
    sound_system: str = Field(default="", alias="Sound - System")
    other_expenses: str = Field(default="", alias="Other Expenses")
    
    # Task 2 & 3: Tracking IDs
    band_event_id: str = Field(default="", alias="Band Event ID")
    public_event_id: str = Field(default="", alias="Public Event ID")
    travel_event_id: str = Field(default="", alias="Travel Event ID")
    departure_time: str = Field(default="", alias="Departure Time")

CSV_HEADERS = [ContractData.model_fields[k].alias or k for k in ContractData.model_fields.keys()]

WORKFLOW_FIELDS = [
    "Discord Finished",
    "Calendar Created",
    "Public Calendar Created",
    "Routing",
    "Mileage",
    "Calendar Start",
    "Calendar End"
]

ALL_HEADERS = CSV_HEADERS + [f for f in WORKFLOW_FIELDS if f not in CSV_HEADERS]

# ------------------------------------------------------------------
# Synchronization
# ------------------------------------------------------------------

def get_master_lock():
    """Returns a FileLock instance for the master CSV."""
    return FileLock(MASTER_CSV_LOCK)
