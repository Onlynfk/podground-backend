-- Migration: Create posts and social features system
-- This creates all tables needed for the home page social feed functionality

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Posts table
CREATE TABLE IF NOT EXISTS public.posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    post_type VARCHAR(50) NOT NULL DEFAULT 'text',
    podcast_episode_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    
    -- Counts (denormalized for performance)
    likes_count INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    shares_count INTEGER DEFAULT 0,
    saves_count INTEGER DEFAULT 0,
    
    -- Indexing
    CONSTRAINT valid_post_type CHECK (post_type IN ('text', 'image', 'video', 'audio', 'poll'))
);

-- Post media items
CREATE TABLE IF NOT EXISTS public.post_media (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    type VARCHAR(50) NOT NULL,
    thumbnail_url TEXT,
    duration INTEGER, -- seconds for audio/video
    width INTEGER,
    height INTEGER,
    position INTEGER DEFAULT 0, -- for ordering multiple media items
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_media_type CHECK (type IN ('image', 'video', 'audio'))
);

-- Post interactions - Likes
CREATE TABLE IF NOT EXISTS public.post_likes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(post_id, user_id)
);

-- Post interactions - Comments
CREATE TABLE IF NOT EXISTS public.post_comments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    parent_comment_id UUID REFERENCES public.post_comments(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    
    -- Denormalized counts
    replies_count INTEGER DEFAULT 0,
    likes_count INTEGER DEFAULT 0
);

-- Comment likes
CREATE TABLE IF NOT EXISTS public.comment_likes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comment_id UUID NOT NULL REFERENCES public.post_comments(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(comment_id, user_id)
);

-- Post saves (bookmarks)
CREATE TABLE IF NOT EXISTS public.post_saves (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(post_id, user_id)
);

-- Post shares
CREATE TABLE IF NOT EXISTS public.post_shares (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    share_type VARCHAR(50) DEFAULT 'internal', -- internal, twitter, facebook, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User connections (following/network)
CREATE TABLE IF NOT EXISTS public.user_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    follower_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    following_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,
    
    UNIQUE(follower_id, following_id),
    CONSTRAINT valid_status CHECK (status IN ('pending', 'accepted', 'rejected', 'blocked')),
    CONSTRAINT no_self_follow CHECK (follower_id != following_id)
);

-- Topics/Categories for content
CREATE TABLE IF NOT EXISTS public.topics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    slug VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    icon_url TEXT,
    follower_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User topic follows
CREATE TABLE IF NOT EXISTS public.user_topic_follows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES public.topics(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, topic_id)
);

-- Post topics (many-to-many)
CREATE TABLE IF NOT EXISTS public.post_topics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES public.topics(id) ON DELETE CASCADE,
    
    UNIQUE(post_id, topic_id)
);

-- Resources
CREATE TABLE IF NOT EXISTS public.resources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    type VARCHAR(50) NOT NULL,
    url TEXT,
    image_url TEXT,
    author VARCHAR(255),
    read_time INTEGER, -- minutes
    is_featured BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_resource_type CHECK (type IN ('article', 'video', 'guide', 'tool'))
);

-- Events
CREATE TABLE IF NOT EXISTS public.events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    host_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ,
    location TEXT,
    is_online BOOLEAN DEFAULT FALSE,
    url TEXT,
    image_url TEXT,
    attendee_count INTEGER DEFAULT 0,
    is_featured BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Event attendees
CREATE TABLE IF NOT EXISTS public.event_attendees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'attending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(event_id, user_id),
    CONSTRAINT valid_attendee_status CHECK (status IN ('attending', 'interested', 'not_attending'))
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_posts_user_id ON public.posts(user_id);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON public.posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_media_post_id ON public.post_media(post_id);
CREATE INDEX IF NOT EXISTS idx_post_likes_post_id ON public.post_likes(post_id);
CREATE INDEX IF NOT EXISTS idx_post_likes_user_id ON public.post_likes(user_id);
CREATE INDEX IF NOT EXISTS idx_post_comments_post_id ON public.post_comments(post_id);
CREATE INDEX IF NOT EXISTS idx_post_saves_user_id ON public.post_saves(user_id);
CREATE INDEX IF NOT EXISTS idx_user_connections_follower_id ON public.user_connections(follower_id);
CREATE INDEX IF NOT EXISTS idx_user_connections_following_id ON public.user_connections(following_id);
CREATE INDEX IF NOT EXISTS idx_user_connections_status ON public.user_connections(status);

-- Enable RLS on all tables
ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_media ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_likes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.comment_likes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_saves ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_topic_follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_attendees ENABLE ROW LEVEL SECURITY;

-- RLS Policies

-- Posts: Users can view all non-deleted posts, edit their own
CREATE POLICY "Posts are viewable by everyone" ON public.posts
    FOR SELECT USING (deleted_at IS NULL);

CREATE POLICY "Users can create their own posts" ON public.posts
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own posts" ON public.posts
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own posts" ON public.posts
    FOR DELETE USING (auth.uid() = user_id);

-- Post media: Same as posts
CREATE POLICY "Post media viewable by everyone" ON public.post_media
    FOR SELECT USING (EXISTS (
        SELECT 1 FROM public.posts WHERE posts.id = post_media.post_id AND deleted_at IS NULL
    ));

CREATE POLICY "Users can manage their post media" ON public.post_media
    FOR ALL USING (EXISTS (
        SELECT 1 FROM public.posts WHERE posts.id = post_media.post_id AND posts.user_id = auth.uid()
    ));

-- Interactions: Users can see all, manage their own
CREATE POLICY "Anyone can view likes" ON public.post_likes
    FOR SELECT USING (true);

CREATE POLICY "Users can manage their likes" ON public.post_likes
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Anyone can view comments" ON public.post_comments
    FOR SELECT USING (deleted_at IS NULL);

CREATE POLICY "Users can create comments" ON public.post_comments
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their comments" ON public.post_comments
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their comments" ON public.post_comments
    FOR DELETE USING (auth.uid() = user_id);

-- Saves: Users can only see/manage their own
CREATE POLICY "Users can manage their saves" ON public.post_saves
    FOR ALL USING (auth.uid() = user_id);

-- Connections: Complex policies for privacy
CREATE POLICY "Users can see their connections" ON public.user_connections
    FOR SELECT USING (
        auth.uid() = follower_id OR auth.uid() = following_id
    );

CREATE POLICY "Users can create connection requests" ON public.user_connections
    FOR INSERT WITH CHECK (auth.uid() = follower_id);

CREATE POLICY "Users can update connection status" ON public.user_connections
    FOR UPDATE USING (auth.uid() = following_id OR auth.uid() = follower_id);

-- Topics: Public read, admin write
CREATE POLICY "Anyone can view topics" ON public.topics
    FOR SELECT USING (true);

-- Resources: Public read, admin write  
CREATE POLICY "Anyone can view resources" ON public.resources
    FOR SELECT USING (true);

-- Events: Public read, hosts can manage
CREATE POLICY "Anyone can view events" ON public.events
    FOR SELECT USING (true);

CREATE POLICY "Users can create events" ON public.events
    FOR INSERT WITH CHECK (auth.uid() = host_user_id);

CREATE POLICY "Hosts can update their events" ON public.events
    FOR UPDATE USING (auth.uid() = host_user_id);