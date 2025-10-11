const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const isDev = process.env.NODE_ENV !== "production";

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  // Always use development server for now
  mainWindow.loadURL("http://localhost:3000");
  mainWindow.webContents.openDevTools();
}

// Handle file selection
ipcMain.handle("select-file", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [
      { name: "UFDR Files", extensions: ["ufdr"] },
      { name: "All Files", extensions: ["*"] },
    ],
  });

  if (!result.canceled && result.filePaths.length > 0) {
    return result.filePaths[0];
  }
  return null;
});

app.whenReady().then(createWindow);
