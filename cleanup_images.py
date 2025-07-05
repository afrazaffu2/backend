#!/usr/bin/env python
"""
Django management script to clean up orphaned image files.
Run this script to remove image files that are no longer referenced in the database.
"""

import os
import django
from django.conf import settings
from django.core.files.storage import default_storage
from events.models import EventImage

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'event_backend.settings')
django.setup()

def cleanup_orphaned_images():
    """Remove image files that are no longer referenced in the database"""
    print("Starting image cleanup...")
    
    # Get all image files in the media directory
    media_root = settings.MEDIA_ROOT
    events_dir = os.path.join(media_root, 'events')
    
    if not os.path.exists(events_dir):
        print("No events directory found. Nothing to clean up.")
        return
    
    # Get all image files from filesystem
    filesystem_images = set()
    for root, dirs, files in os.walk(events_dir):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                # Get relative path from media root
                rel_path = os.path.relpath(os.path.join(root, file), media_root)
                filesystem_images.add(rel_path)
    
    # Get all image files from database
    db_images = set()
    for event_image in EventImage.objects.all():
        if event_image.image:
            # Get relative path from media root
            rel_path = os.path.relpath(event_image.image.path, media_root)
            db_images.add(rel_path)
    
    # Find orphaned files (in filesystem but not in database)
    orphaned_files = filesystem_images - db_images
    
    if not orphaned_files:
        print("No orphaned image files found.")
        return
    
    print(f"Found {len(orphaned_files)} orphaned image files:")
    
    # Ask for confirmation
    response = input("Do you want to delete these files? (y/N): ")
    if response.lower() != 'y':
        print("Cleanup cancelled.")
        return
    
    # Delete orphaned files
    deleted_count = 0
    for file_path in orphaned_files:
        full_path = os.path.join(media_root, file_path)
        try:
            os.remove(full_path)
            print(f"Deleted: {file_path}")
            deleted_count += 1
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")
    
    print(f"Cleanup completed. Deleted {deleted_count} files.")

def list_image_usage():
    """List all images and their usage"""
    print("Current image usage:")
    print("-" * 50)
    
    for event_image in EventImage.objects.select_related('event').all():
        print(f"Event: {event_image.event.title}")
        print(f"Type: {event_image.image_type}")
        print(f"File: {event_image.image.name if event_image.image else 'No file'}")
        print(f"Path: {event_image.image.path if event_image.image else 'No path'}")
        print("-" * 30)

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'list':
        list_image_usage()
    else:
        cleanup_orphaned_images() 