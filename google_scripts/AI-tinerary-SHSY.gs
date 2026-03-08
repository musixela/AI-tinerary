/**
 * AI-tinerary: Google Sheets Sync (SHSY)
 * 
 * Logic: "Upsert" based on Starting Date + Venue composite key.
 * This preserves manual formatting and extra columns/notes.
 */

// === CONFIG ===
var SYNC_DRIVE_FOLDER_ID = 'PASTE_DRIVE_FOLDER_ID_HERE';
var TARGET_SPREADSHEET_ID = 'PASTE_TARGET_SPREADSHEET_ID_HERE';
var MASTER_CSV_NAME = 'master-output.csv';
var TARGET_SHEET_NAME = 'Master Output';

function syncMasterToSheets() {
  // 1. Resolve CSV File
  var folderId = extractId(SYNC_DRIVE_FOLDER_ID);
  var folder = DriveApp.getFolderById(folderId);
  var files = folder.getFilesByName(MASTER_CSV_NAME);
  if (!files.hasNext()) return;
  var file = files.next();
  
  // 2. Parse CSV
  var csvString = file.getBlob().getDataAsString();
  var csvData = Utilities.parseCsv(csvString);
  if (!csvData || csvData.length < 2) return; // Header + at least one row

  var headers = csvData[0];
  var dateIdx = headers.indexOf('Starting Date');
  var venueIdx = headers.indexOf('Venue');
  var timeIdx = headers.indexOf('Time');

  if (dateIdx === -1 || venueIdx === -1 || timeIdx === -1) {
    Logger.log('Error: Starting Date, Venue, or Time column missing in CSV.');
    return;
  }

  // 3. Resolve Spreadsheet & Sheet
  var ss = SpreadsheetApp.openById(extractId(TARGET_SPREADSHEET_ID));
  var sheet = ss.getSheetByName(TARGET_SHEET_NAME) || ss.insertSheet(TARGET_SHEET_NAME);

  // 4. Load Existing Data from Sheet
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  var sheetData = lastRow > 0 ? sheet.getRange(1, 1, lastRow, Math.max(lastCol, headers.length)).getValues() : [];
  
  // Map existing rows by Date + Venue
  var sheetMap = {};
  var sheetHeaders = [];
  if (sheetData.length > 0) {
    sheetHeaders = sheetData[0];
    var sDateIdx = sheetHeaders.indexOf('Starting Date');
    var sVenueIdx = sheetHeaders.indexOf('Venue');
    var sTimeIdx = sheetHeaders.indexOf('Time');
    
    for (var i = 1; i < sheetData.length; i++) {
      var key = sheetData[i][sDateIdx] + '|' + sheetData[i][sVenueIdx] + '|' + sheetData[i][sTimeIdx];
      sheetMap[key] = i + 1; // 1-based row index
    }
  } else {
    // Initial setup: write headers
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheetHeaders = headers;
  }

  // 5. Upsert Logic
  for (var j = 1; j < csvData.length; j++) {
    var row = csvData[j];
    var key = row[dateIdx] + '|' + row[venueIdx] + '|' + row[timeIdx];
    
    // Prepare row for writing (match sheet column order)
    var writeRow = [];
    for (var k = 0; k < sheetHeaders.length; k++) {
      var headerName = sheetHeaders[k];
      var csvColIdx = headers.indexOf(headerName);
      if (csvColIdx !== -1) {
        writeRow.push(row[csvColIdx]);
      } else {
        writeRow.push(null); // Preserve manual columns
      }
    }

    if (sheetMap[key]) {
      // Update existing row (only overwrite columns present in CSV)
      var targetRow = sheetMap[key];
      for (var col = 0; col < writeRow.length; col++) {
        if (writeRow[col] !== null) {
          sheet.getRange(targetRow, col + 1).setValue(writeRow[col]);
        }
      }
    } else {
      // Append new row
      sheet.appendRow(writeRow);
    }
  }
  
  Logger.log('Sync complete.');
}

function extractId(input) {
  if (input.indexOf('http') === -1) return input;
  if (input.indexOf('folders/') !== -1) return input.split('folders/')[1].split('/')[0].split('?')[0];
  if (input.indexOf('/d/') !== -1) return input.split('/d/')[1].split('/')[0].split('?')[0];
  return input;
}
