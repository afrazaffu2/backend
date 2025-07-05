from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework import routers

from hosts.views import HostViewSet
from events.views import EventViewSet, BookingViewSet, hitpay_transactions
from hosts.views import host_login
from events.views import events_by_host
from events.views import events_stats_by_host
from events.views import events_yearly_count_by_host
from events.views import event_by_slug
from events.views import bookings_by_event, register_for_event, scan_qr_by_sno, get_booking_by_sno
from events.views import filtered_events, upcoming_ongoing_events, bookings_by_host

router = routers.DefaultRouter(trailing_slash=False)
router.register(r'hosts', HostViewSet, basename='host')
router.register(r'events', EventViewSet, basename='event')
router.register(r'bookings', BookingViewSet, basename='booking')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/hosts/login', host_login),
    # Custom event URLs - these must come BEFORE the router
    path('api/events/host/<str:host_id>', events_by_host),
    path('api/events/host/<str:host_id>/stats', events_stats_by_host),
    path('api/events/host/<str:host_id>/yearly', events_yearly_count_by_host),
    path('api/events/slug/<str:slug>', event_by_slug),
    path('api/events/filtered', filtered_events),
    path('api/events/upcoming-ongoing', upcoming_ongoing_events),
    path('api/events/<int:event_id>/bookings', bookings_by_event),
    path('api/events/<int:event_id>/register', register_for_event),
    # Booking endpoints
    path('api/bookings/sno/<str:sno>', get_booking_by_sno),
    path('api/bookings/sno/<str:sno>/scan', scan_qr_by_sno),
    path('api/bookings/host/<str:host_id>', bookings_by_host),
    # Router URLs come last
    path('api/', include(router.urls)),
    path('api/', include('categories.urls')),
    path('api/', include('amenities.urls')),
    path('api/hitpay-transactions/', hitpay_transactions, name='hitpay_transactions'),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 