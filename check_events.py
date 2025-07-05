#!/usr/bin/env python
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'event_backend.settings')
django.setup()

from events.models import Event

# Check all events
events = Event.objects.all()
print(f"Total events in database: {events.count()}")

for event in events:
    print(f"ID: {event.id}, Title: {event.title}, Slug: {event.slug}, Published: {event.is_published}")

# Check if 'testss' slug exists
try:
    test_event = Event.objects.get(slug='testss')
    print(f"\nFound event with slug 'testss': {test_event.title}")
except Event.DoesNotExist:
    print("\nNo event found with slug 'testss'")
    
    # Show available slugs
    print("\nAvailable slugs:")
    for event in events:
        print(f"  - {event.slug}") 