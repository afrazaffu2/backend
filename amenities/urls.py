from rest_framework.routers import DefaultRouter
from .views import AmenityViewSet

router = DefaultRouter(trailing_slash=False)
router.register(r'amenities', AmenityViewSet, basename='amenity')
 
urlpatterns = router.urls 