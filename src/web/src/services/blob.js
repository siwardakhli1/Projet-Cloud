import axios from "axios";

export async function uploadFileToBlob(uploadUrl, file) {
    await axios.put(uploadUrl, file, {
        headers: {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": file.type || "application/octet-stream",
        },
    });
}