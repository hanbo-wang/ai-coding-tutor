from pydantic import BaseModel


class AttachmentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    file_type: str
    url: str


class UploadBatchOut(BaseModel):
    files: list[AttachmentOut]


class UploadLimitsOut(BaseModel):
    max_images: int
    max_documents: int
    max_image_bytes: int
    max_document_bytes: int
    image_extensions: list[str]
    document_extensions: list[str]
    accept_extensions: list[str]
