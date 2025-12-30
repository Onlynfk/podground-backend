# Post Update Implementation - Full State Approach

## Overview
Implemented full caller control over post updates using the "Full State" approach (Option B). The caller specifies which existing media to keep, and the backend deletes everything else.

## API Design

### Endpoint
`PUT /api/v1/posts/{post_id}`

### Parameters (Form-data mode)

#### Text Content
- **`content`** (string, optional): New text content. If provided, replaces existing content. Empty string clears content.

#### Media Management
- **`keep_media_ids`** (JSON array, optional): Array of media IDs to keep
  - If **not provided**: existing media is unchanged
  - If **provided**: only media in this list is kept, all others are deleted
  - Example: `["uuid-1", "uuid-2", "uuid-3"]`

- **`files`** (file[], optional): New files to upload and add (max 10 files)
- **`media_urls_json`** (JSON array, optional): Pre-uploaded media URLs to add

#### Other Fields
- **`post_type`** (string, optional): "text", "image", "video", "audio"
- **`podcast_episode_url`** (string, optional): URL to podcast episode

## Backend Implementation

### Changes Made

**1. main.py (lines 3182-3273)**
- Added `keep_media_ids` parameter parsing
- Validates JSON array format
- Passes to `update_post()` function

**2. supabase_posts_client.py (lines 855-948)**
- Enhanced `update_post()` function with media management logic
- Steps:
  1. Fetch all current media IDs for the post
  2. Calculate which to delete: `media_to_delete = current_ids - keep_ids`
  3. Delete media not in keep list
  4. Add new media items

### Backend Logic Flow

```python
if "keep_media_ids" in update_data:
    keep_media_ids = update_data["keep_media_ids"]

    # Get current media
    current_media = get_media_for_post(post_id)
    current_ids = [m.id for m in current_media]

    # Calculate what to delete
    to_delete = [id for id in current_ids if id not in keep_media_ids]

    # Delete unwanted media
    if to_delete:
        delete_media(to_delete)

# Add new media
if "media_items" in update_data:
    for item in update_data["media_items"]:
        insert_media(item)
```

## Frontend Implementation

### Changes Made

**1. State Management (lines 74-80)**
```typescript
const [editingPost, setEditingPost] = useState<Post | null>(null);
const [mediaToRemove, setMediaToRemove] = useState<Set<string>>(new Set());
```

**2. Edit Functions (lines 221-249)**
- `startEditPost()`: Initialize edit state with post data
- `cancelEdit()`: Clear all edit state
- `toggleMediaRemoval()`: Mark/unmark media for removal using Set

**3. Update Request (lines 251-313)**
```typescript
// Calculate keep_media_ids
const existingMedia = editingPost.media_items || [];
const keepMediaIds = existingMedia
  .filter(media => !mediaToRemove.has(media.id))
  .map(media => media.id);

// Only send if user marked any for removal
if (mediaToRemove.size > 0) {
  formData.append('keep_media_ids', JSON.stringify(keepMediaIds));
}
```

**4. UI Updates (lines 529-571)**
- Grid display of existing media (4 columns)
- Click to toggle removal (red border + X overlay)
- Counter showing how many items marked for removal
- Hover effects for better UX

## Usage Examples

### Example 1: Edit text only
```javascript
// User edits text, doesn't touch media
formData.append('content', 'Updated text');
// keep_media_ids not sent = no media changes
```

### Example 2: Remove 2 images, keep 3
```javascript
// Post has media: [id1, id2, id3, id4, id5]
// User clicks id2 and id4 to remove them
// mediaToRemove = Set(['id2', 'id4'])

const keepMediaIds = ['id1', 'id3', 'id5'];
formData.append('keep_media_ids', JSON.stringify(keepMediaIds));
```

### Example 3: Remove all existing media
```javascript
// User clicks all media to remove them
// mediaToRemove = Set(['id1', 'id2', 'id3'])

const keepMediaIds = []; // Empty array
formData.append('keep_media_ids', JSON.stringify([]));
```

### Example 4: Remove 1 image and add 2 new ones
```javascript
// User removes id2, uploads 2 new files
const keepMediaIds = ['id1', 'id3'];
formData.append('keep_media_ids', JSON.stringify(keepMediaIds));
formData.append('files', newFile1);
formData.append('files', newFile2);

// Result: Post has [id1, id3, newFile1, newFile2]
```

### Example 5: Clear text and remove all media
```javascript
formData.append('content', ''); // Clear text
formData.append('keep_media_ids', JSON.stringify([])); // Remove all media
```

### Example 6: Replace all media
```javascript
// Remove all existing, add new
formData.append('keep_media_ids', JSON.stringify([]));
formData.append('files', newFile1);
formData.append('files', newFile2);
```

## Key Benefits

1. **Simple mental model**: Frontend tracks "what to keep", not complex operations
2. **Frontend already has the data**: Media IDs are in the post response
3. **Atomic operation**: All changes happen in one request
4. **No edge cases**: Clear behavior for all scenarios
5. **Efficient**: Only one query to get current media, one to delete unwanted

## Files Modified

### Backend
- `/backend/main.py` (lines 3182-3273)
- `/backend/supabase_posts_client.py` (lines 855-948)

### Frontend
- `/nextjs-test-client/pages/test-posts.tsx` (lines 74-588)

## Testing Scenarios

- [x] Edit text only (no media changes)
- [x] Add new images without touching existing
- [x] Remove specific images
- [x] Remove all images
- [x] Replace all media with new files
- [x] Clear text content
- [x] Edit text + remove images + add new images (complex scenario)
- [x] Cancel edit (state cleanup)

## Technical Notes

### Why Set instead of Array for mediaToRemove?
- Fast O(1) lookups with `.has()`
- Easy toggle with `.add()` and `.delete()`
- No duplicates automatically

### Why only send keep_media_ids if mediaToRemove.size > 0?
- Optimization: Don't send unnecessary data
- Preserves backward compatibility
- If user doesn't interact with media, existing behavior (append only) is maintained

### Database Operations
1. `SELECT id FROM post_media WHERE post_id = ?` - Get current media
2. `DELETE FROM post_media WHERE id IN (?)` - Delete unwanted media
3. `INSERT INTO post_media (...)` - Add new media

All operations are wrapped in the existing transaction handling.

## Cache Invalidation
Feed cache is automatically invalidated after successful post update via:
```python
self.feed_cache.invalidate_via_database()
```

## Security Considerations
- Ownership verified before any updates
- Only media belonging to the post can be deleted
- File upload limits enforced (max 10 files)
- JSON validation for keep_media_ids parameter
