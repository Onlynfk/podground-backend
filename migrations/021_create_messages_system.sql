-- Messages System Database Schema
-- Comprehensive messaging platform with voice messages, attachments, and real-time features

-- Create conversations table
CREATE TABLE IF NOT EXISTS public.conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Conversation metadata
    title VARCHAR(255), -- Optional custom title
    conversation_type VARCHAR(20) DEFAULT 'direct', -- 'direct', 'group', 'podcast_discussion'
    
    -- Podcast context (for podcast-related conversations)
    podcast_id UUID, -- References podcasts table from Listen system
    episode_id UUID, -- References episodes table from Listen system
    
    -- Participants count (denormalized for performance)
    participant_count INTEGER DEFAULT 0,
    
    -- Last activity
    last_message_at TIMESTAMPTZ DEFAULT NOW(),
    last_message_id UUID,
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create conversation participants table
CREATE TABLE IF NOT EXISTS public.conversation_participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Participant settings
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    left_at TIMESTAMPTZ,
    is_admin BOOLEAN DEFAULT FALSE,
    
    -- Notification settings
    notifications_enabled BOOLEAN DEFAULT TRUE,
    mute_until TIMESTAMPTZ,
    
    -- Reading status
    last_read_at TIMESTAMPTZ DEFAULT NOW(),
    last_read_message_id UUID,
    
    UNIQUE(conversation_id, user_id)
);

-- Create messages table
CREATE TABLE IF NOT EXISTS public.messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    sender_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Message content
    message_type VARCHAR(20) DEFAULT 'text', -- 'text', 'voice', 'image', 'video', 'file', 'podcast_share'
    content TEXT, -- Text content or caption
    
    -- Voice message specific
    voice_duration_seconds INTEGER, -- Duration for voice messages
    voice_waveform JSONB, -- Waveform data for visualization
    
    -- File attachments
    attachment_url TEXT, -- URL to uploaded file
    attachment_type VARCHAR(20), -- 'image', 'video', 'audio', 'document'
    attachment_filename VARCHAR(255), -- Original filename
    attachment_size BIGINT, -- File size in bytes
    attachment_mime_type VARCHAR(100),
    
    -- Podcast sharing
    shared_podcast_id UUID, -- When sharing podcast content
    shared_episode_id UUID, -- When sharing episode content
    
    -- Message metadata
    edited_at TIMESTAMPTZ,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    
    -- Thread/reply support
    reply_to_message_id UUID REFERENCES public.messages(id),
    thread_message_count INTEGER DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Search
    search_vector tsvector
);

-- Create message reactions table
CREATE TABLE IF NOT EXISTS public.message_reactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES public.messages(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Reaction details
    reaction_type VARCHAR(50) NOT NULL, -- 'like', 'love', 'laugh', 'wow', 'sad', 'angry', 'thumbs_up', etc.
    emoji VARCHAR(10), -- Unicode emoji if custom reaction
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(message_id, user_id, reaction_type)
);

-- Create user online status table
CREATE TABLE IF NOT EXISTS public.user_online_status (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Status tracking
    is_online BOOLEAN DEFAULT FALSE,
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    status_message VARCHAR(255), -- Custom status message
    
    -- Presence details
    device_type VARCHAR(20), -- 'web', 'mobile', 'desktop'
    user_agent TEXT,
    
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create message delivery status table (for read receipts)
CREATE TABLE IF NOT EXISTS public.message_delivery_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES public.messages(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Delivery tracking
    delivered_at TIMESTAMPTZ DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    
    UNIQUE(message_id, user_id)
);

-- Create conversation settings table
CREATE TABLE IF NOT EXISTS public.conversation_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- User-specific conversation settings
    custom_name VARCHAR(255), -- User's custom name for the conversation
    is_pinned BOOLEAN DEFAULT FALSE,
    is_archived BOOLEAN DEFAULT FALSE,
    is_muted BOOLEAN DEFAULT FALSE,
    mute_until TIMESTAMPTZ,
    
    -- Notification preferences
    notification_sound VARCHAR(50) DEFAULT 'default',
    show_previews BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(conversation_id, user_id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_conversations_last_message ON public.conversations(last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_podcast ON public.conversations(podcast_id) WHERE podcast_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_episode ON public.conversations(episode_id) WHERE episode_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_conversation_participants_user ON public.conversation_participants(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_participants_conversation ON public.conversation_participants(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_participants_active ON public.conversation_participants(conversation_id, user_id) WHERE left_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON public.messages(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON public.messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_messages_type ON public.messages(message_type);
CREATE INDEX IF NOT EXISTS idx_messages_search ON public.messages USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON public.messages(reply_to_message_id) WHERE reply_to_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_message_reactions_message ON public.message_reactions(message_id);
CREATE INDEX IF NOT EXISTS idx_message_reactions_user ON public.message_reactions(user_id);

CREATE INDEX IF NOT EXISTS idx_user_online_status_online ON public.user_online_status(is_online) WHERE is_online = true;

CREATE INDEX IF NOT EXISTS idx_message_delivery_message ON public.message_delivery_status(message_id);
CREATE INDEX IF NOT EXISTS idx_message_delivery_user ON public.message_delivery_status(user_id);

CREATE INDEX IF NOT EXISTS idx_conversation_settings_user ON public.conversation_settings(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_settings_pinned ON public.conversation_settings(user_id, is_pinned) WHERE is_pinned = true;

-- Enable Row Level Security
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message_reactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_online_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message_delivery_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_settings ENABLE ROW LEVEL SECURITY;

-- RLS Policies for conversations
CREATE POLICY "Users can view conversations they participate in" 
ON public.conversations FOR SELECT 
USING (
    id IN (
        SELECT conversation_id 
        FROM public.conversation_participants 
        WHERE user_id = auth.uid() AND left_at IS NULL
    )
);

CREATE POLICY "Users can create conversations" 
ON public.conversations FOR INSERT 
WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Participants can update conversations" 
ON public.conversations FOR UPDATE 
USING (
    id IN (
        SELECT conversation_id 
        FROM public.conversation_participants 
        WHERE user_id = auth.uid() AND left_at IS NULL
    )
);

-- RLS Policies for conversation participants
CREATE POLICY "Users can view participants in their conversations" 
ON public.conversation_participants FOR SELECT 
USING (
    conversation_id IN (
        SELECT conversation_id 
        FROM public.conversation_participants 
        WHERE user_id = auth.uid() AND left_at IS NULL
    )
);

CREATE POLICY "Users can manage their own participation" 
ON public.conversation_participants FOR ALL 
USING (user_id = auth.uid());

-- RLS Policies for messages
CREATE POLICY "Users can view messages in their conversations" 
ON public.messages FOR SELECT 
USING (
    conversation_id IN (
        SELECT conversation_id 
        FROM public.conversation_participants 
        WHERE user_id = auth.uid() AND left_at IS NULL
    )
);

CREATE POLICY "Users can create messages in their conversations" 
ON public.messages FOR INSERT 
WITH CHECK (
    sender_id = auth.uid() AND
    conversation_id IN (
        SELECT conversation_id 
        FROM public.conversation_participants 
        WHERE user_id = auth.uid() AND left_at IS NULL
    )
);

CREATE POLICY "Users can update their own messages" 
ON public.messages FOR UPDATE 
USING (sender_id = auth.uid());

-- RLS Policies for message reactions
CREATE POLICY "Users can view reactions in their conversations" 
ON public.message_reactions FOR SELECT 
USING (
    message_id IN (
        SELECT m.id 
        FROM public.messages m
        JOIN public.conversation_participants cp ON m.conversation_id = cp.conversation_id
        WHERE cp.user_id = auth.uid() AND cp.left_at IS NULL
    )
);

CREATE POLICY "Users can manage their own reactions" 
ON public.message_reactions FOR ALL 
USING (user_id = auth.uid());

-- RLS Policies for online status
CREATE POLICY "Users can view online status of conversation participants" 
ON public.user_online_status FOR SELECT 
USING (
    user_id IN (
        SELECT DISTINCT cp2.user_id
        FROM public.conversation_participants cp1
        JOIN public.conversation_participants cp2 ON cp1.conversation_id = cp2.conversation_id
        WHERE cp1.user_id = auth.uid() AND cp1.left_at IS NULL AND cp2.left_at IS NULL
    )
);

CREATE POLICY "Users can manage their own online status" 
ON public.user_online_status FOR ALL 
USING (user_id = auth.uid());

-- RLS Policies for delivery status
CREATE POLICY "Users can view delivery status for their messages" 
ON public.message_delivery_status FOR SELECT 
USING (
    message_id IN (
        SELECT id 
        FROM public.messages 
        WHERE sender_id = auth.uid()
    ) OR user_id = auth.uid()
);

CREATE POLICY "Users can manage delivery status for messages they receive" 
ON public.message_delivery_status FOR ALL 
USING (user_id = auth.uid());

-- RLS Policies for conversation settings
CREATE POLICY "Users can manage their own conversation settings" 
ON public.conversation_settings FOR ALL 
USING (user_id = auth.uid());

-- Functions for message search vectors
CREATE OR REPLACE FUNCTION update_message_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', 
        COALESCE(NEW.content, '') || ' ' || 
        COALESCE(NEW.attachment_filename, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for message search vectors
CREATE TRIGGER message_search_vector_trigger
    BEFORE INSERT OR UPDATE ON public.messages
    FOR EACH ROW EXECUTE FUNCTION update_message_search_vector();

-- Function to update conversation participant count
CREATE OR REPLACE FUNCTION update_conversation_participant_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE public.conversations 
        SET participant_count = participant_count + 1 
        WHERE id = NEW.conversation_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE public.conversations 
        SET participant_count = participant_count - 1 
        WHERE id = OLD.conversation_id;
    ELSIF TG_OP = 'UPDATE' THEN
        -- Handle participant leaving/rejoining
        IF OLD.left_at IS NULL AND NEW.left_at IS NOT NULL THEN
            -- Participant left
            UPDATE public.conversations 
            SET participant_count = participant_count - 1 
            WHERE id = NEW.conversation_id;
        ELSIF OLD.left_at IS NOT NULL AND NEW.left_at IS NULL THEN
            -- Participant rejoined
            UPDATE public.conversations 
            SET participant_count = participant_count + 1 
            WHERE id = NEW.conversation_id;
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for participant count updates
CREATE TRIGGER update_participant_count_trigger
    AFTER INSERT OR UPDATE OR DELETE ON public.conversation_participants
    FOR EACH ROW EXECUTE FUNCTION update_conversation_participant_count();

-- Function to update conversation last message info
CREATE OR REPLACE FUNCTION update_conversation_last_message()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE public.conversations 
        SET 
            last_message_at = NEW.created_at,
            last_message_id = NEW.id,
            updated_at = NEW.created_at
        WHERE id = NEW.conversation_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for last message updates
CREATE TRIGGER update_last_message_trigger
    AFTER INSERT ON public.messages
    FOR EACH ROW EXECUTE FUNCTION update_conversation_last_message();

-- Function to update thread message count
CREATE OR REPLACE FUNCTION update_thread_message_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.reply_to_message_id IS NOT NULL THEN
        UPDATE public.messages 
        SET thread_message_count = thread_message_count + 1 
        WHERE id = NEW.reply_to_message_id;
    ELSIF TG_OP = 'DELETE' AND OLD.reply_to_message_id IS NOT NULL THEN
        UPDATE public.messages 
        SET thread_message_count = thread_message_count - 1 
        WHERE id = OLD.reply_to_message_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for thread count updates
CREATE TRIGGER update_thread_count_trigger
    AFTER INSERT OR DELETE ON public.messages
    FOR EACH ROW EXECUTE FUNCTION update_thread_message_count();