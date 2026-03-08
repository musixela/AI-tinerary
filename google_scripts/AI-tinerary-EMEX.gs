// === CONFIG ===
// Gmail label that marks confirmed show emails
var SOURCE_LABEL_NAME = 'Confirmed Shows';

// Gmail label used to mark processed threads
var PROCESSED_LABEL_NAME = 'Confirmed Shows - Processed';

// Drive folder ID that is synced locally to:
// /code/Email Export/Contracts/Incoming
// Example URL: https://drive.google.com/drive/folders/XXXXXXXX
var INCOMING_DRIVE_FOLDER_ID = 'PASTE_DRIVE_FOLDER_ID_HERE';
var COMPLETE_DRIVE_FOLDER_ID = 'PASTE_DRIVE_FOLDER_ID_HERE';

function saveConfirmedShowsAttachmentsToDrive() {
  var sourceLabel = GmailApp.getUserLabelByName(SOURCE_LABEL_NAME);
  if (!sourceLabel) {
    Logger.log('Source label not found: ' + SOURCE_LABEL_NAME);
    return;
  }

  var processedLabel = GmailApp.getUserLabelByName(PROCESSED_LABEL_NAME);
  if (!processedLabel) {
    processedLabel = GmailApp.createLabel(PROCESSED_LABEL_NAME);
  }

  var targetFolder = DriveApp.getFolderById(INCOMING_DRIVE_FOLDER_ID);

  // Get all threads with the label
  var threads = sourceLabel.getThreads();
  if (threads.length === 0) {
    Logger.log('No threads with label: ' + SOURCE_LABEL_NAME);
    return;
  }

  threads.forEach(function (thread) {
    // Skip if already processed
    if (thread.hasLabel(processedLabel)) {
      return;
    }

    var messages = thread.getMessages();
    messages.forEach(function (message) {
      var attachments = message.getAttachments();
      attachments.forEach(function (att) {
        // Only save PDFs and .eml-like things if you want to feed them to your pipeline
        var name = att.getName() || 'attachment';
        var lower = name.toLowerCase();

        if (
          lower.endsWith('.pdf') ||
          lower.endsWith('.eml') ||
          lower.endsWith('.msg') // optional, in case some clients send .msg
        ) {
          // Build a descriptive filename so your Python script logs are useful
          var dateStr = Utilities.formatDate(
            message.getDate(),
            Session.getScriptTimeZone(),
            'yyyyMMdd_HHmmss'
          );
          var safeSubject = (message.getSubject() || '')
            .replace(/[\\/:*?"<>|]/g, '')
            .substring(0, 80);
          var newName = dateStr + ' - ' + safeSubject + ' - ' + name;

          targetFolder.createFile(att.copyBlob()).setName(newName);
        }
      });
    });

    // Mark this thread as processed so you don't get duplicates
    thread.addLabel(processedLabel);
  });
}
// ------------------------------------------------------------------
// Helper to clear the drive folder after local processing
// ------------------------------------------------------------------
/**
 * Empties files from the **complete** folder specified by
 * `COMPLETE_DRIVE_FOLDER_ID` by moving them to trash, but only
 * if they have been in the folder for more than 15 days.
 */
function cleanupDriveFolder() {
  var folder = DriveApp.getFolderById(COMPLETE_DRIVE_FOLDER_ID);
  var files = folder.getFiles();
  var now = new Date();
  var retentionDays = 15;
  var cutoffTime = now.getTime() - (retentionDays * 24 * 60 * 60 * 1000);

  while (files.hasNext()) {
    var file = files.next();
    // Use dateCreated as the reference for how long it's been in the folder
    if (file.getDateCreated().getTime() < cutoffTime) {
      Logger.log('Trashing old file: ' + file.getName());
      file.setTrashed(true);
    } else {
      Logger.log('Retaining file (less than 15 days old): ' + file.getName());
    }
  }
}
