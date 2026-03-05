# AI-tinerary

Itinerary-AI is a Python-based utility designed to parse contract emails and spreadsheets, extract event details, and generate CSV outputs for planning and scheduling band itineraries. It simplifies the process of converting unstructured data from email files into structured data that can be used for touring logistics.

## 📁 Repository Structure

```
AI-tinerary/
├── CSV-COMBINER.py          # Script to merge multiple CSV outputs
├── Itinerary-Spreadsheet-8.py  # Current main script for itinerary parsing
├── requirements.txt         # Python dependencies
├── Contracts/               # Raw .eml contract files
├── Outputs/                 # Generated CSV files after parsing
└── __pycache__/             # Python cache files (ignored by git)
```

> Note: The repository is organized around the `Itinerary-Spreadsheet-8.py` script which reads email files and produces CSV outputs stored under `Outputs/`.

## 🚀 Getting Started

1. **Clone the repository**
   ```bash
   git clone https://github.com/<yourusername>/AI-tinerary.git
   cd AI-tinerary
   ```

2. **Create a Python virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Prepare your data**
   - Place `.eml` contract files into the `Contracts/` directory.
   - The parsing script will output CSVs to the `Outputs/` directory.

5. **Run the main script**
   ```bash
   python Itinerary-Spreadsheet-8.py
   ```

## 🛠️ Features

- Parses email contracts for event metadata (dates, venues, offers).
- Generates individual CSVs per contract and a master CSV.
- Combines multiple CSV files with `CSV-COMBINER.py`.

## ⚙️ Configuration

- Modify `requirements.txt` to adjust Python package dependencies.
- Update the scripts to handle new email formats or additional fields.

## 📄 License

This project is released under the GPL License. See `LICENSE` for details.

## 🤝 Contributing

Feel free to submit issues or pull requests. Before contributing, ensure that your changes are aligned with the project goals and include appropriate tests or documentation updates.


---
