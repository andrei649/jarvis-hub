export const documentDirectory='file:///fixture/', cacheDirectory='file:///fixture/';
export const EncodingType={Base64:'base64'};
export const writeAsStringAsync=async()=>{};
export const deletedFiles: string[] = [];
export const deleteAsync = async (uri: string) => { deletedFiles.push(uri); };
