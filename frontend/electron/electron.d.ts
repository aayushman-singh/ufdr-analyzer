export interface ElectronAPI {
  selectFile: () => Promise<string | null>;
}

declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}
