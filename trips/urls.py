from rest_framework import routers
from .views import TripViewSet

router = routers.DefaultRouter()
router.register(r'trips', TripViewSet)

urlpatterns = router.urls
