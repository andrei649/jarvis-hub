export const documentDirectory = 'file:///fixture/', cacheDirectory = 'file:///fixture/';
export const EncodingType = { Base64: 'base64' };
export const written: string[] = [];
export const copied: { from: string; to: string }[] = [];
export const deletedFiles: string[] = [];
/** Both native feature suites observe the same deletion log. */
export const deleted = deletedFiles;
export const writeAsStringAsync = async (uri: string) => { written.push(uri); };
export const copyAsync = async ({ from, to }: { from: string; to: string }) => { copied.push({ from, to }); };
export const deleteAsync = async (uri: string) => { deletedFiles.push(uri); };
