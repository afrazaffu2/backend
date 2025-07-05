from rest_framework import viewsets, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from .models import Host
from .serializers import HostSerializer


class HostViewSet(viewsets.ModelViewSet):
    """API endpoint that allows hosts to be viewed or edited."""

    # type: ignore[attr-defined]
    queryset = Host.objects.all()  # type: ignore[attr-defined]
    serializer_class = HostSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []  # Disable default SessionAuthentication to avoid CSRF during dev 

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def host_login(request):
    email = request.data.get('email')
    password = request.data.get('password')
    if not email or not password:
        return Response({'detail': 'Email and password required.'}, status=status.HTTP_400_BAD_REQUEST)
    if password != 'host@123':
        return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
    try:
        host = Host.objects.get(email=email)  # type: ignore[attr-defined]
    except Host.DoesNotExist:  # type: ignore[attr-defined]
        return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
    return Response({'id': str(host.id), 'email': host.email, 'name': host.name, 'role': 'host'}, status=status.HTTP_200_OK) 