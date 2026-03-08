// === CONFIG ===
// The ID of the Drive Folder where master-output.csv is synced.
// You can use the full URL or just the ID.
// Example: https://drive.google.com/drive/folders/XXXXXXXX
var SYNC_DRIVE_FOLDER_ID = 'PASTE_DRIVE_FOLDER_ID_HERE';

// The ID of the Google Sheet to sync to.
// Example: https://docs.google.com/spreadsheets/d/1vYnSXXXXXXXXXXXXXXXX/edit
var TARGET_SPREADSHEET_ID = 'PASTE_TARGET_SPREADSHEET_ID_HERE';

// Name of the CSV file expected in Google Drive
var MASTER_CSV_NAME = 'master-output.csv';

// Name of the tab in the Spreadsheet to write to
var TARGET_SHEET_NAME = 'Master Output';

/**
 * Main function to sync the master-output.csv from Google Drive 
 * into a specific Google Sheet.
 */
function syncMasterToSheets() {
  // 1. Resolve Folder
  var folderId = extractId(SYNC_DRIVE_FOLDER_ID);
  var folder;
  try {
    folder = DriveApp.getFolderById(folderId);
  } catch (e) {
    Logger.log('Error finding folder: ' + e.message);
    return;
  }

  // 2. Find CSV file
  var files = folder.getFilesByName(MASTER_CSV_NAME);
  if (!files.hasNext()) {
    Logger.log('No file found with name: ' + MASTER_CSV_NAME);
    return;
  }

  var file = files.next();
  
  // 3. Parse CSV Data
  var csvString = file.getBlob().getDataAsString();
  var csvData;
  try {
    csvData = Utilities.parseCsv(csvString);
  } catch (e) {
    Logger.log('Error parsing CSV: ' + e.message);
    return;
  }
  
  if (!csvData || csvData.length === 0) {
    Logger.log('CSV data is empty.');
    return;
  }

  // 4. Resolve Spreadsheet
  var ssId = extractId(TARGET_SPREADSHEET_ID);
  var ss;
  try {
    ss = SpreadsheetApp.openById(ssId);
  } catch (e) {
    Logger.log('Error opening Spreadsheet: ' + e.message);
    return;
  }

  // 5. Resolve Sheet (Tab)
  var sheet = ss.getSheetByName(TARGET_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(TARGET_SHEET_NAME);
    Logger.log('Created new sheet: ' + TARGET_SHEET_NAME);
  }

  // 6. Write Data
  // Clear existing content and write new data from the top
  sheet.clear();
  sheet.getRange(1, 1, csvData.length, csvData[0].length).setValues(csvData);
  
  Logger.log('Sync complete. ' + csvData.length + ' rows synced to ' + TARGET_SHEET_NAME);
}

/**
 * Helper to extract ID from a full Google Drive/Docs URL if provided.
 */
function extractId(input) {
  if (input.indexOf('http') === -1) return input; // Already an ID
  
  // Try folders pattern
  if (input.indexOf('folders/') !== -1) {
    return input.split('folders/')[1].split('/')[0].split('?')[0];
  }
  
  // Try spreadsheets pattern
  if (input.indexOf('/d/') !== -1) {
    return input.split('/d/')[1].split('/')[0].split('?')[0];
  }
  
  return input;
}

/**
 * (Optional) Create a time-based trigger to run this every hour.
 */
function createSyncTrigger() {
  // Check if trigger already exists
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === 'syncMasterToSheets') {
      return;
    }
  }
  
  // Create trigger for every hour
  ScriptApp.newTrigger('syncMasterToSheets')
    .timeBased()
    .everyHours(1)
    .create();
}
