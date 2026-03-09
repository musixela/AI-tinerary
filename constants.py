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
PROMPTS_DIR = ROOT_DIR / "Prompts"

# Ensure directories exist
for d in [PROCESSED_DIR, BACKUPS_DIR, LOGS_DIR, CONTRACTS_DIR, COMPLETE_DIR, OUTPUTS_DIR, BITS_DIR, ITINERARIES_DIR, PROMPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Schema & Headers
# ------------------------------------------------------------------

class ContractData(BaseModel):
    """Pydantic model to strictly enforce the output schema and defaults."""
    model_config = ConfigDict(populate_by_name=True)

    starting_date: str = Field(default="", alias="Starting Date", description="First performance date. Prefer M/D format (e.g. '5/8'). Use the earliest date if multiple are given.")
    ending_date: str = Field(default="", alias="Ending Date", description="Last performance date for multi-day runs/festivals. Empty string for single shows.")
    venue: str = Field(default="", alias="Venue", description="Physical venue name (e.g. 'Downtown Commons'). If a series name is present (e.g. 'SAILS Series at The Stage'), use 'The Stage' here.")
    location: str = Field(default="", alias="Location", description="City and state (e.g. 'Hickory, NC').")
    booking: str = Field(default="TRUE", alias="Booking", description="'TRUE' if a booking contact or talent buyer is present. Default to 'TRUE' unless specifically stated as self-booked or no agent.")
    mgmt: str = Field(default="FALSE", alias="MGMT", description="'TRUE' if a manager or management company is mentioned. Otherwise 'FALSE'.")
    door_deal: str = Field(default="FALSE", alias="Door Deal", description="'TRUE' if pay is a percentage/split of ticket sales (e.g. '70/30 split'). 'FALSE' if it is a flat guarantee.")
    dd_notes: str = Field(default="", alias="DD Notes", description="Details of the door deal, splits, caps, or minimums.")
    hospitality: str = Field(default="", alias="Hospitality", description="Food, drinks, and rider info. Example: 'Food: $25 buyout. Drinks: Water provided.'")
    contact_name: str = Field(default="", alias="Contact Name", description="Name of the main day-of-show contact or email sign-off person.")
    contact_details: str = Field(default="", alias="Contact Details", description="Phone and/or email for the contact person.")
    other_details: str = Field(default="", alias="Other Details", description="Radius clauses, weather plans, series names, parking, or any other useful notes.")
    address: str = Field(default="", alias="Address", description="Full street address of the venue, including city, state, and zip.")
    accommodations: str = Field(default="", alias="Accomodations", description="Description of lodging arrangements (e.g. '2 double rooms').")
    accom_address: str = Field(default="", alias="Accom Address", description="Full address of the lodging/hotel if specified.")
    est_mileage: str = Field(default="", alias="Est. Mileage", description="ALWAYS leave as empty string. Do not attempt to calculate.")
    time: str = Field(default="", alias="Time", description="Main show start time (e.g. '7:00 PM').")
    doors: str = Field(default="", alias="Doors", description="Door opening time if specified.")
    load_in: str = Field(default="", alias="Load In", description="Load-in/Soundcheck time.")
    pay: str = Field(default="", alias="Pay", description="Guaranteed fee amount (e.g. '$950.00').")
    sound_person: str = Field(default="", alias="Sound - Person", description="Name of the sound engineer or sound company.")
    sound_system: str = Field(default="", alias="Sound - System", description="Description of the PA system (e.g. 'House PA provided').")
    other_expenses: str = Field(default="", alias="Other Expenses", description="Extra costs like parking or marketing fees.")
    
    # Task 2 & 3: Tracking IDs
    band_event_id: str = Field(default="", alias="Band Event ID", description="Leave as empty string.")
    public_event_id: str = Field(default="", alias="Public Event ID", description="Leave as empty string.")
    travel_event_id: str = Field(default="", alias="Travel Event ID", description="Leave as empty string.")
    departure_time: str = Field(default="", alias="Departure Time", description="Leave as empty string.")

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
