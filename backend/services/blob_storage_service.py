from azure.storage.blob import BlobServiceClient
import config
from datetime import datetime

class BlobStorageService:
    def __init__(self):
        self.connection_string = config.AZURE_STORAGE_CONNECTION_STRING
        self.container_name = config.AZURE_STORAGE_CONTAINER_NAME
        self.blob_service_client = BlobServiceClient.from_connection_string(
            self.connection_string
        )
        self.container_client = self.blob_service_client.get_container_client(
            self.container_name
        )
    
    async def upload_file(self, file_content: bytes, filename: str, session_id: str = None) -> dict:
        """
        Upload file to Azure Blob Storage
        
        Args:
            file_content: Binary content of the file
            filename: Original filename
            session_id: Optional session ID to organize files
            
        Returns:
            dict with upload status and blob name
        """
        try:
            # Create unique blob name with timestamp
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            
            # Organize by session if provided
            if session_id:
                blob_name = f"uploads/{session_id}/{timestamp}_{filename}"
            else:
                blob_name = f"uploads/{timestamp}_{filename}"
            
            # Upload to blob storage
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            blob_client.upload_blob(file_content, overwrite=True)
            
            return {
                "success": True,
                "blob_name": blob_name,
                "url": blob_client.url,
                "filename": filename
            }
            
        except Exception as e:
            print(f"Error uploading {filename}: {e}")
            return {
                "success": False,
                "error": str(e),
                "filename": filename
            }
    
    async def delete_session_files(self, session_id: str) -> dict:
        """
        Delete all files uploaded in a specific session
        
        Args:
            session_id: Session ID to delete files for
            
        Returns:
            dict with deletion status and count
        """
        try:
            deleted_count = 0
            prefix = f"uploads/{session_id}/"
            
            # List all blobs with the session prefix
            blob_list = self.container_client.list_blobs(name_starts_with=prefix)
            
            # Delete each blob
            for blob in blob_list:
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name,
                    blob=blob.name
                )
                blob_client.delete_blob()
                deleted_count += 1
                print(f"Deleted blob: {blob.name}")
            
            return {
                "success": True,
                "deleted_count": deleted_count,
                "session_id": session_id
            }
            
        except Exception as e:
            print(f"Error deleting session files for {session_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "deleted_count": 0,
                "session_id": session_id
            }