-- Migration: Add document support to temp_media_uploads
-- This allows uploading PDF, DOC, DOCX, TXT, XLS, XLSX files

-- Drop the existing constraint
ALTER TABLE public.temp_media_uploads 
DROP CONSTRAINT IF EXISTS valid_file_type;

-- Add the new constraint with document support
ALTER TABLE public.temp_media_uploads 
ADD CONSTRAINT valid_file_type CHECK (file_type IN ('image', 'video', 'audio', 'document'));

-- Add comment to document the change
COMMENT ON COLUMN public.temp_media_uploads.file_type IS 
'Type of media file: image, video, audio, or document';

-- Update the generate_secure_media_path function to handle documents
-- (The existing function already works for documents, no changes needed)