-- Migration: Create database functions for counter management
-- This creates functions to safely increment/decrement counters

-- Function to increment post likes count
CREATE OR REPLACE FUNCTION increment_post_likes(post_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.posts 
  SET likes_count = likes_count + 1 
  WHERE id = post_id;
END;
$$ LANGUAGE plpgsql;

-- Function to decrement post likes count
CREATE OR REPLACE FUNCTION decrement_post_likes(post_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.posts 
  SET likes_count = GREATEST(0, likes_count - 1) 
  WHERE id = post_id;
END;
$$ LANGUAGE plpgsql;

-- Function to increment post comments count
CREATE OR REPLACE FUNCTION increment_post_comments(post_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.posts 
  SET comments_count = comments_count + 1 
  WHERE id = post_id;
END;
$$ LANGUAGE plpgsql;

-- Function to decrement post comments count
CREATE OR REPLACE FUNCTION decrement_post_comments(post_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.posts 
  SET comments_count = GREATEST(0, comments_count - 1) 
  WHERE id = post_id;
END;
$$ LANGUAGE plpgsql;

-- Function to increment post saves count
CREATE OR REPLACE FUNCTION increment_post_saves(post_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.posts 
  SET saves_count = saves_count + 1 
  WHERE id = post_id;
END;
$$ LANGUAGE plpgsql;

-- Function to decrement post saves count
CREATE OR REPLACE FUNCTION decrement_post_saves(post_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.posts 
  SET saves_count = GREATEST(0, saves_count - 1) 
  WHERE id = post_id;
END;
$$ LANGUAGE plpgsql;

-- Function to increment post shares count
CREATE OR REPLACE FUNCTION increment_post_shares(post_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.posts 
  SET shares_count = shares_count + 1 
  WHERE id = post_id;
END;
$$ LANGUAGE plpgsql;

-- Function to increment comment replies count
CREATE OR REPLACE FUNCTION increment_comment_replies(comment_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.post_comments 
  SET replies_count = replies_count + 1 
  WHERE id = comment_id;
END;
$$ LANGUAGE plpgsql;

-- Function to increment comment likes count
CREATE OR REPLACE FUNCTION increment_comment_likes(comment_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.post_comments 
  SET likes_count = likes_count + 1 
  WHERE id = comment_id;
END;
$$ LANGUAGE plpgsql;

-- Function to decrement comment likes count
CREATE OR REPLACE FUNCTION decrement_comment_likes(comment_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.post_comments 
  SET likes_count = GREATEST(0, likes_count - 1) 
  WHERE id = comment_id;
END;
$$ LANGUAGE plpgsql;

-- Grant execute permissions to authenticated users
GRANT EXECUTE ON FUNCTION increment_post_likes(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION decrement_post_likes(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_post_comments(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION decrement_post_comments(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_post_saves(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION decrement_post_saves(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_post_shares(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_comment_replies(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_comment_likes(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION decrement_comment_likes(UUID) TO authenticated;