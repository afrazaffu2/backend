from django.shortcuts import render
from rest_framework import viewsets
from .models import Amenity
from .serializers import AmenitySerializer

# Create your views here.

class AmenityViewSet(viewsets.ModelViewSet):
    queryset = Amenity.objects.all().order_by('-created_at')
    serializer_class = AmenitySerializer
