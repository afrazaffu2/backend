from django.shortcuts import render
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .models import Event, EventImage, Booking, Payment, EmergencyContact
from .serializers import EventSerializer, EventImageSerializer, BookingSerializer
from hosts.models import Host
from django.utils import timezone
from django.db.models.functions import ExtractYear
from django.db.models import Count
from datetime import datetime, timedelta
import os
import json
import urllib.parse
import requests
import base64
from django.core.mail import send_mail, EmailMultiAlternatives, EmailMessage
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Create your views here.

def _generate_additional_attendees_html(booking):
    """Generate HTML for additional attendees section"""
    if not booking.additional_members or len(booking.additional_members) == 0:
        return ''
    
    members_html = ''
    for member in booking.additional_members:
        members_html += f"""
        <div style='margin-bottom:12px;padding:12px;background:#fef7ed;border-radius:6px;border-left:4px solid #f59e0b;'>
          <p style='margin:0 0 4px 0;font-weight:600;color:#92400e;font-size:14px;'>{member.get('name', '')}</p>
          <p style='margin:0 0 2px 0;color:#b45309;font-size:13px;'>📧 {member.get('email', '')}</p>
          <p style='margin:0;color:#b45309;font-size:13px;'>📞 {member.get('phone', 'Not provided')}</p>
        </div>
        """
    
    return f"""
    <div style='background:linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);border-radius:12px;padding:20px 32px 20px 32px;margin:0 24px 24px 24px;border:1px solid #f59e0b;'>
      <h3 style='color:#92400e;margin:0 0 16px 0;font-size:16px;font-weight:600;'>👥 Additional Attendees ({len(booking.additional_members)})</h3>
      <div style='background:#fff;border-radius:8px;padding:16px;border:1px solid #fbbf24;'>
        {members_html}
      </div>
    </div>
    """

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()  # type: ignore[attr-defined]
    serializer_class = EventSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []  # Disable default SessionAuthentication to avoid CSRF during dev
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _cleanup_old_image(self, event_image):
        """Safely delete old image file from filesystem"""
        if event_image and event_image.image:
            try:
                # Get the file path
                file_path = event_image.image.path
                # Delete the file if it exists
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                # Log error but don't fail the operation
                print(f"Error deleting old image file: {e}")

    def create(self, request, *args, **kwargs):
        # Handle FormData with JSON data
        if 'data' in request.data:
            # Parse JSON data from FormData
            try:
                data = json.loads(request.data['data'])
            except (json.JSONDecodeError, TypeError):
                return Response({'error': 'Invalid JSON data'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            data = request.data.copy()
        
        # Handle image files separately
        image_files = {}
        for key in ['cover', 'thumbnail', 'square']:
            if key in request.FILES:
                image_files[key] = request.FILES[key]
        
        # Remove image files from data to avoid JSON serialization issues
        for key in image_files.keys():
            data.pop(key, None)
        
        # Create event first
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save()
        
        # Handle image uploads
        for image_type, image_file in image_files.items():
            # Delete existing image of this type if it exists
            existing_images = EventImage.objects.filter(event=event, image_type=image_type)
            for existing_image in existing_images:
                self._cleanup_old_image(existing_image)
            existing_images.delete()
            
            # Create new image with unique filename
            EventImage.objects.create(
                event=event,
                image_type=image_type,
                image=image_file
            )
        
        # Return the created event with image URLs
        return_serializer = self.get_serializer(event, context={'request': request})
        return Response(return_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Handle image files separately
        image_files = {}
        for key in ['cover', 'thumbnail', 'square']:
            if key in request.FILES:
                image_files[key] = request.FILES[key]
        
        # Remove image files from data to avoid JSON serialization issues
        data = request.data.copy()
        for key in image_files.keys():
            data.pop(key, None)
        
        # Update event
        serializer = self.get_serializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        event = serializer.save()
        
        # Handle image uploads
        for image_type, image_file in image_files.items():
            # Delete existing image of this type if it exists
            existing_images = EventImage.objects.filter(event=event, image_type=image_type)
            for existing_image in existing_images:
                self._cleanup_old_image(existing_image)
            existing_images.delete()
            
            # Create new image with unique filename
            EventImage.objects.create(
                event=event,
                image_type=image_type,
                image=image_file
            )
        
        # Return the updated event with image URLs
        return_serializer = self.get_serializer(event)
        return Response(return_serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Delete event and clean up all associated images"""
        instance = self.get_object()
        
        # Clean up all image files for this event
        for event_image in instance.event_images.all():
            self._cleanup_old_image(event_image)
        
        # Delete the event (this will cascade delete EventImage records)
        instance.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)

class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def create(self, request, *args, **kwargs):
        """Create a new booking with QR code generation"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        
        # Generate QR code
        booking.generate_qr_code()
        booking.save()
        
        # Return the created booking with QR code URL
        return_serializer = self.get_serializer(booking, context={'request': request})
        return Response(return_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def scan_qr(self, request, pk=None):
        """Scan QR code and toggle booking activation status"""
        booking = self.get_object()
        
        # Toggle the boolean status
        booking.is_activated = not booking.is_activated
        booking.save()
        
        serializer = self.get_serializer(booking, context={'request': request})
        return Response({
            'booking': serializer.data,
            'is_activated': booking.is_activated,
            'status': booking.status,
            'message': f"Booking {booking.sno} {'activated' if booking.is_activated else 'deactivated'} successfully"
        })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def events_by_host(request, host_id):
    events = Event.objects.filter(assigned_host=host_id)  # type: ignore[attr-defined]
    serializer = EventSerializer(events, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def events_stats_by_host(request, host_id):
    now = timezone.now()
    events = Event.objects.filter(assigned_host=host_id)  # type: ignore[attr-defined]
    total = events.count()
    ongoing = events.filter(date__lte=now, end_date__gt=now).count()
    upcoming = events.filter(date__gt=now).count()
    return Response({
        'total': total,
        'ongoing': ongoing,
        'upcoming': upcoming,
    })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def events_yearly_count_by_host(request, host_id):
    events = Event.objects.filter(assigned_host=host_id)  # type: ignore[attr-defined]
    # Group by year
    yearly_counts = (
        events.annotate(year=ExtractYear('date'))
        .values('year')
        .annotate(count=Count('id'))
        .order_by('year')
    )
    return Response(list(yearly_counts))

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def event_by_slug(request, slug):
    try:
        event = Event.objects.get(slug=slug)  # type: ignore[attr-defined]
        user = request.user if request.user and request.user.is_authenticated else None
        # Allow if published
        if event.is_published:
            serializer = EventSerializer(event, context={'request': request})
            return Response(serializer.data)
        # Allow if admin
        if user and hasattr(user, 'is_superuser') and user.is_superuser:
            serializer = EventSerializer(event, context={'request': request})
            return Response(serializer.data)
        # Allow if host and assigned to this event
        if user and hasattr(user, 'id') and hasattr(event, 'assigned_host') and str(event.assigned_host.id) == str(user.id):
            serializer = EventSerializer(event, context={'request': request})
            return Response(serializer.data)
        # Otherwise, not published
        return Response({'error': 'Event not published'}, status=status.HTTP_404_NOT_FOUND)
    except Event.DoesNotExist:  # type: ignore[attr-defined]
        return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def bookings_by_event(request, event_id):
    """Get all bookings for a specific event"""
    bookings = Booking.objects.filter(event_id=event_id)
    serializer = BookingSerializer(bookings, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def register_for_event(request, event_id):
    """Register for an event with enhanced data"""
    try:
        event = Event.objects.get(id=event_id)
    except Event.DoesNotExist:
        return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Get host information - use event's assigned host if no host_id provided
    host_id = request.data.get('host_id')
    print(f"Received host_id: {host_id}")
    print(f"Event assigned host: {event.assigned_host.id}")
    host = event.assigned_host  # Default to event's assigned host
    if host_id and host_id != event.assigned_host.id:
        try:
            host = Host.objects.get(id=host_id)
            print(f"Found host: {host.name}")
        except Host.DoesNotExist:
            host = event.assigned_host  # Fallback to event's assigned host
            print(f"Host not found, using event host: {host.name}")
    else:
        print(f"Using event's assigned host: {host.name}")
    
    # Create emergency contact if provided
    emergency_contact = None
    emergency_contact_data = request.data.get('emergency_contact')
    if emergency_contact_data:
        emergency_contact = EmergencyContact.objects.create(
            name=emergency_contact_data.get('name', ''),
            phone=emergency_contact_data.get('phone', ''),
            relationship=emergency_contact_data.get('relationship', '')
        )
    
    # Prepare booking data
    booking_data = {
        'event': event_id,
        'host': host.id,
        'event_title': request.data.get('event_title', event.title),
        'event_date': request.data.get('event_date', event.date),
        'event_location': request.data.get('event_location', event.location),
        'user_name': request.data.get('user_name'),
        'email': request.data.get('email'),
        'phone': request.data.get('phone', ''),
        'member_count': request.data.get('member_count', 1),
        'selected_package': request.data.get('selected_package', {}),
        'food_preference': request.data.get('food_preference', ''),
        'additional_members': request.data.get('additional_members', []),
        'emergency_contact': emergency_contact,
        'special_requirements': request.data.get('special_requirements', ''),
        'payment_method': request.data.get('payment_method', 'paynow'),
        'payment_status': request.data.get('payment_status', 'pending'),
        'payment_amount': request.data.get('total_amount', 0.00),
        'payment_currency': request.data.get('payment_currency', 'SGD'),
        'terms_accepted': request.data.get('terms_accepted', False),
        'privacy_policy_accepted': request.data.get('privacy_policy_accepted', False),
        'ip_address': request.META.get('REMOTE_ADDR'),
        'user_agent': request.META.get('HTTP_USER_AGENT', ''),
        'source': request.data.get('source', 'web'),
        'total_amount': request.data.get('total_amount', 0.00),
    }
    
    print(f"Received total_amount from frontend: {request.data.get('total_amount')}")
    print(f"Booking data being sent to serializer: {booking_data}")
    serializer = BookingSerializer(data=booking_data)
    if serializer.is_valid():
        booking = serializer.save()
        # Generate QR code
        booking.generate_qr_code()
        booking.save()
        
        # Send confirmation email (HTML with QR and activation link)
        try:
            subject = f'🎉 Welcome to {event.title}! Your Ticket is Here'
            from_email = None  # Uses DEFAULT_FROM_EMAIL
            to = [booking.email]

            # Activation URL and QR code
            from django.conf import settings
            frontend_url = getattr(settings, 'FRONTEND_URL', 'https://event-management-fe.onrender.com')
            activation_url = f"{frontend_url}/activate/{booking.sno}"
            qr_code_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(activation_url)}"
            print(f"Frontend URL: {frontend_url}")
            print(f"Activation URL: {activation_url}")
            print(f"QR Code URL: {qr_code_api_url}")

            # Fetch QR code image and save to media directory
            qr_img_base64 = ""
            qr_img_bytes = None
            qr_img_url = ""
            try:
                qr_response = requests.get(qr_code_api_url)
                print(f"QR API Response Status: {qr_response.status_code}")
                print(f"QR API Response Content Length: {len(qr_response.content) if qr_response.content else 0}")
                
                if qr_response.status_code == 200 and qr_response.content:
                    qr_img_bytes = qr_response.content
                    qr_img_base64 = base64.b64encode(qr_response.content).decode('utf-8')
                    print(f"QR Base64 Length: {len(qr_img_base64)}")
                    print(f"QR Image Bytes Length: {len(qr_img_bytes)}")
                    
                    # Save QR code to media directory
                    import os
                    from django.conf import settings
                    
                    qr_filename = f"qr_codes/{booking.sno}_qr.png"
                    qr_path = os.path.join(settings.MEDIA_ROOT, qr_filename)
                    os.makedirs(os.path.dirname(qr_path), exist_ok=True)
                    
                    with open(qr_path, 'wb') as f:
                        f.write(qr_img_bytes)
                    
                    # Create URL for the saved image
                    qr_img_url = f"{frontend_url}/media/{qr_filename}"
                    print(f"QR image saved to: {qr_path}")
                    print(f"QR image URL: {qr_img_url}")
                else:
                    print(f"Failed to fetch QR code: Status {qr_response.status_code}")
            except Exception as e:
                print(f"Error fetching QR code image: {e}")
                import traceback
                traceback.print_exc()

            # Generate PDF ticket with a bordered, vertical table and clear layout
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
            elements = []
            styles = getSampleStyleSheet()
            normal = styles['Normal']
            normal.fontSize = 11
            normal.leading = 15
            bold = ParagraphStyle('Bold', parent=normal, fontName='Helvetica-Bold')

            # Page border (drawn after build)
            def draw_border(canvas, doc):
                canvas.saveState()
                canvas.setStrokeColor(colors.HexColor('#4f46e5'))
                canvas.setLineWidth(3)
                canvas.rect(18, 18, doc.pagesize[0]-36, doc.pagesize[1]-36)
                canvas.restoreState()

            # Table data (vertical, field name + value)
            table_data = [
                [Paragraph('<b>Primary Attendee:</b>', bold), Paragraph(str(getattr(booking, 'user_name', '')), normal)],
                [Paragraph('<b>Email:</b>', bold), Paragraph(str(getattr(booking, 'email', '')), normal)],
                [Paragraph('<b>Phone:</b>', bold), Paragraph(str(getattr(booking, 'phone', '') or 'Not provided'), normal)],
                [Paragraph('<b>Ticket ID:</b>', bold), Paragraph(str(booking.sno), normal)],
                [Paragraph('<b>Total Attendees:</b>', bold), Paragraph(str(booking.member_count), normal)],
                [Paragraph('<b>Amount Paid:</b>', bold), Paragraph(f"₹{booking.total_amount}", normal)],
                [Paragraph('<b>Status:</b>', bold), Paragraph('Confirmed', normal)],
                [Paragraph('<b>Event Name:</b>', bold), Paragraph(str(getattr(event, 'title', '')), normal)],
                [Paragraph('<b>Event Location:</b>', bold), Paragraph(str(getattr(event, 'location', '')), normal)],
                [Paragraph('<b>Date & Time:</b>', bold), Paragraph(
                    f"{event.date.strftime('%B %d, %Y – %I:%M %p') if hasattr(event, 'date') and event.date else 'TBA'}" +
                    (f" to {event.end_date.strftime('%I:%M %p')}" if hasattr(event, 'end_date') and event.end_date else ''),
                    normal
                )],
            ]
            
            # Add food preference if available
            if booking.food_preference:
                table_data.append([Paragraph('<b>Food Preference:</b>', bold), Paragraph(str(booking.food_preference), normal)])
            
            # Add additional members if any
            if booking.additional_members and len(booking.additional_members) > 0:
                table_data.append([Paragraph('<b>Additional Attendees:</b>', bold), Paragraph(f"{len(booking.additional_members)} registered", normal)])
            table = Table(table_data, colWidths=[1.7*inch, 4.2*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#4f46e5')),
                ('TEXTCOLOR', (0, 0), (1, 0), colors.white),
                ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (1, 0), 12),
                ('ALIGN', (0, 0), (1, 0), 'LEFT'),
                ('BACKGROUND', (0, 1), (1, -1), colors.HexColor('#f3f4f6')),
                ('TEXTCOLOR', (0, 1), (1, -1), colors.HexColor('#22223b')),
                ('FONTNAME', (0, 1), (1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (1, -1), 11),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOX', (0, 0), (-1, -1), 1.2, colors.HexColor('#4f46e5')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#a5b4fc')),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 18))

            # Additional Attendees Section
            if booking.additional_members and len(booking.additional_members) > 0:
                elements.append(Paragraph('👥 <b>Additional Attendees:</b>', bold))
                elements.append(Spacer(1, 10))
                
                # Create table for additional attendees
                additional_data = [['Name', 'Email', 'Phone']]
                for i, member in enumerate(booking.additional_members, 1):
                    additional_data.append([
                        str(member.get('name', '')),
                        str(member.get('email', '')),
                        str(member.get('phone', 'Not provided'))
                    ])
                
                additional_table = Table(additional_data, colWidths=[2*inch, 2.5*inch, 1.4*inch])
                additional_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#374151')),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 9),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#4f46e5')),
                    ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#a5b4fc')),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]))
                elements.append(additional_table)
            elements.append(Spacer(1, 18))

            # QR code section
            elements.append(Paragraph('🧾 <b>Scan the QR code below at the venue for entry:</b>', normal))
            elements.append(Spacer(1, 10))
            if qr_img_bytes:
                qr_img = Image(io.BytesIO(qr_img_bytes), width=120, height=120)
                qr_img.hAlign = 'CENTER'
                elements.append(qr_img)
                elements.append(Spacer(1, 16))

            # Support/contact info
            support_email = getattr(event, 'support_email', 'support@yourevent.com')
            event_site = 'www.youreventsite.com'
            venue_map_url = f'https://maps.google.com/?q={urllib.parse.quote(getattr(event, "location", ""))}'
            contact_info = f"""
            <para align='center'>
            <font size=11>📞 Contact Support: <a href='mailto:{support_email}' color='#4f46e5'>{support_email}</a> |
            📍 <a href='{venue_map_url}' color='#4f46e5'>Venue Map</a><br/>
            🌐 Visit: <a href='https://{event_site}' color='#4f46e5'>{event_site}</a></font>
            </para>
            """
            elements.append(Spacer(1, 10))
            elements.append(Paragraph(contact_info, styles['Normal']))

            doc.build(elements, onFirstPage=draw_border, onLaterPages=draw_border)
            pdf = pdf_buffer.getvalue()
            pdf_buffer.close()

            text_content = f"""Your ticket has been registered successfully!\nTicket ID: {booking.sno}\nAmount: {booking.total_amount}\nActivation URL: {activation_url}\n"""

            # Convert QR image to base64 for inline embedding
            qr_base64 = ""
            if qr_img_bytes:
                qr_base64 = base64.b64encode(qr_img_bytes).decode('utf-8')
                print(f"Final QR Base64 Length: {len(qr_base64)}")
                print(f"QR Base64 starts with: {qr_base64[:50]}...")
            else:
                print("No QR image bytes available for base64 conversion")

            # Show the PNG image in email body using base64, and also attach it as file
            qr_img_html = ""
            if qr_img_bytes:
                # Convert to base64 for inline display
                qr_base64 = base64.b64encode(qr_img_bytes).decode('utf-8')
                qr_img_html = f'''
                <div style="text-align:center; margin:20px 0;">
                    <p style="color:#4f46e5; font-size:16px; font-weight:600; margin-bottom:16px;">📎 QR Code (Also Attached Below)</p>
                    <img src="data:image/png;base64,{qr_base64}" alt="QR Code" style="width:180px;height:180px;border:4px solid #a5b4fc;display:block;margin:0 auto 16px auto;background:#fff;border-radius:8px;" />
                    <div style="background:#f8f9fa; border:2px dashed #dee2e6; border-radius:8px; padding:12px; margin:8px 0;">
                        <p style="color:#6c757d; font-size:13px; margin:0;">📎 qr_code_{booking.sno}.png (attached file)</p>
                    </div>
                </div>
                '''
                print("QR image displayed in email body and will be attached")
            else:
                qr_img_html = '<p style="color:#888; font-size:14px; text-align:center;">QR Code not available</p>'
                print("Using fallback QR message")
            
            html_content = f"""
            <html>
              <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Event Registration Confirmation</title>
              </head>
              <body style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #f8fafc; margin:0; padding:20px; line-height:1.6;'>
                <div style='max-width:500px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 10px 25px rgba(0,0,0,0.1);overflow:hidden;'>
                  <!-- Friendly Welcome Message -->
                  <div style='padding:32px 32px 10px 32px;'>
                    <p style='font-size:17px; color:#222; margin:0 0 18px 0;'>Hi <strong>{booking.user_name}</strong>,</p>
                    <p style='font-size:16px; color:#444; margin:0 0 10px 0;'>Thank you for registering for <strong>{event.title}</strong> – we're thrilled to have you with us!</p>
                    <p style='font-size:16px; color:#444; margin:0 0 10px 0;'>Your ticket has been successfully generated. 🪪<br>Please find it attached below. Don't forget to bring it with you on event day (printed or on your phone).</p>
                    <p style='font-size:16px; color:#444; margin:0 0 10px 0;'>We're preparing something amazing and can't wait to share it with you.</p>
                  </div>
                  <!-- Ticket Info Inline -->
                  <div style='background:#f8fafc;border-radius:12px;padding:20px 32px 20px 32px;margin:0 24px 24px 24px;border:1px solid #e2e8f0;'>
                    <p style="margin:0;font-size:15px;color:#4f46e5;font-weight:600;">
                      <span style="margin-right:32px;"><strong>Ticket ID:</strong> <span style="color:#1e293b;font-weight:700;">{booking.sno}</span></span>
                      <span style="margin-right:32px;"><strong>Total Attendees:</strong> <span style="color:#1e293b;font-weight:700;">{booking.member_count}</span></span>
                      <span><strong>Amount Paid:</strong> <span style="color:#7c3aed;font-weight:700;">₹{booking.total_amount}</span></span>
                    </p>
                  </div>
                  <!-- QR Code Section -->
                  <div style='background:linear-gradient(135deg, #e0e7ff 0%, #f3e8ff 100%);border-radius:12px;padding:20px 32px 20px 32px;margin:0 24px 24px 24px;text-align:center;border:1px solid #c7d2fe;'>
                    <h3 style='color:#4f46e5;margin:0 0 16px 0;font-size:17px;font-weight:600;'>Ticket Activation</h3>
                    {qr_img_html}
                    <div style='margin-top:16px;'>
                      <a href='{activation_url}' style='display:inline-block;padding:10px 28px;background:#4f46e5;color:#fff;font-weight:600;border-radius:8px;text-decoration:none;font-size:15px;'>
                        Activate Ticket
                      </a>
                    </div>
                  </div>
                  <!-- Additional Attendees Section -->
                  {_generate_additional_attendees_html(booking) if booking.additional_members and len(booking.additional_members) > 0 else ''}
                  <!-- Event Details with Map -->
                  <div style='background:#f8fafc;border-radius:12px;padding:20px 32px 20px 32px;margin:0 24px 24px 24px;border:1px solid #e2e8f0;'>
                    <h3 style='color:#1f2937;margin:0 0 10px 0;font-size:16px;font-weight:600;'>Event Details</h3>
                    <div style='color:#374151;font-size:15px;line-height:1.6;margin-bottom:14px;'>
                      <p style='margin:0 0 6px;'><strong>Date:</strong> {event.date.strftime('%B %d, %Y') if hasattr(event, 'date') else 'TBA'}</p>
                      <p style='margin:0 0 6px;'><strong>Time:</strong> {event.date.strftime('%I:%M %p') if hasattr(event, 'date') else 'TBA'}</p>
                      <p style='margin:0;'><strong>Location:</strong> {event.location if hasattr(event, 'location') else 'TBA'}</p>
                    </div>
                    <div style='text-align:center;'>
                      <a href='https://maps.google.com/?q={event.location if hasattr(event, "location") else ""}' target='_blank' style='display:inline-block;text-decoration:none;'>
                        <div style='background:#fff;border-radius:8px;padding:10px 0;border:2px solid #e2e8f0;box-shadow:0 2px 8px rgba(0,0,0,0.07);transition:all 0.3s ease;'>
                          <span style='font-size:32px;color:#6b7280;'>🗺️</span>
                          <div style='color:#4f46e5;font-size:13px;font-weight:600;margin-top:4px;'>View on Google Maps</div>
                        </div>
                      </a>
                    </div>
                  </div>
                  <!-- Friendly Closing Message -->
                  <div style='padding:18px 32px 0 32px;'>
                    <p style='color:#374151;font-size:15px;margin:0 0 0 0;'>See you soon!<br><span style='color:#4f46e5;font-weight:600;'>— The {event.title} Team</span></p>
                  </div>
                  <!-- Simple Footer -->
                  <div style='background:#1f2937;padding:18px 32px;text-align:center;'>
                    <p style='color:#9ca3af;margin:0;font-size:14px;'>Need help? Contact us at <a href='mailto:support@yourdomain.com' style='color:#60a5fa;text-decoration:none;'>support@yourdomain.com</a></p>
                  </div>
                </div>
              </body>
            </html>
            """
            
            print(f"Final HTML content length: {len(html_content)}")
            print(f"QR img HTML in final content: {'{qr_img_html}' in html_content}")
            print(f"QR img HTML length in final content: {len(qr_img_html)}")

            print(f"Attempting to send email to: {booking.email}")
            
                        # Check if email backend is configured
            from django.conf import settings
            if hasattr(settings, 'EMAIL_BACKEND') and settings.EMAIL_BACKEND != 'django.core.mail.backends.dummy.EmailBackend':
                try:
                    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
                    msg.attach_alternative(html_content, "text/html")
                    
                    # Attach the QR code PNG as a separate attachment
                    if qr_img_bytes:
                        msg.attach(f"qr_code_{booking.sno}.png", qr_img_bytes, "image/png")
                        print(f"QR PNG attached: qr_code_{booking.sno}.png")
                    
                    # Attach the PDF as before
                    msg.attach(f"ticket_{booking.sno}.pdf", pdf, "application/pdf")
                    msg.send()
                    print(f"HTML Email sent successfully!")
                except Exception as email_error:
                    print(f"Email sending failed: {email_error}")
                    print("Registration successful, but email notification failed")
            else:
                print("Email backend not configured. Registration successful without email notification.")
                print("To enable email notifications, configure EMAIL_BACKEND in settings.py")
        except Exception as e:
            print(f"Error sending confirmation email: {e}")
            print(f"Error type: {type(e)}")
            import traceback
            traceback.print_exc()
        return_serializer = BookingSerializer(booking, context={'request': request})
        return Response(return_serializer.data, status=status.HTTP_201_CREATED)
    else:
        print(f"Serializer validation errors: {serializer.errors}")
        print(f"Serializer error details: {dict(serializer.errors)}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_booking_by_sno(request, sno):
    """Get a booking by SNO"""
    try:
        booking = Booking.objects.get(sno=sno)
        serializer = BookingSerializer(booking, context={'request': request})
        return Response(serializer.data)
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def scan_qr_by_sno(request, sno):
    """Scan QR code by SNO and toggle booking activation status"""
    try:
        booking = Booking.objects.get(sno=sno)
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Toggle the boolean status
    booking.is_activated = not booking.is_activated
    booking.save()
    
    serializer = BookingSerializer(booking, context={'request': request})
    return Response({
        'booking': serializer.data,
        'is_activated': booking.is_activated,
        'status': booking.status,
        'message': f"Booking {booking.sno} {'activated' if booking.is_activated else 'deactivated'} successfully"
    })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def filtered_events(request):
    """Get events filtered by date range"""
    from datetime import datetime, timedelta
    
    # Get filter type from query parameters
    filter_type = request.query_params.get('filter', 'all')
    host_id = request.query_params.get('host_id', None)
    
    # Start with all events or host-specific events
    if host_id:
        events = Event.objects.filter(assigned_host=host_id)
    else:
        events = Event.objects.all()
    
    # Apply date filtering based on filter type
    if filter_type == 'today':
        today = timezone.now().date()
        events = events.filter(date__date=today)
    elif filter_type == 'last_7_days':
        seven_days_ago = timezone.now().date() - timedelta(days=7)
        events = events.filter(date__date__gte=seven_days_ago)
    elif filter_type == 'last_30_days':
        thirty_days_ago = timezone.now().date() - timedelta(days=30)
        events = events.filter(date__date__gte=thirty_days_ago)
    elif filter_type == 'custom':
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                events = events.filter(date__date__gte=start_date)
            except ValueError:
                return Response({'error': 'Invalid start_date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
        
        if end_date:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                events = events.filter(date__date__lte=end_date)
            except ValueError:
                return Response({'error': 'Invalid end_date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Order by date
    events = events.order_by('date')
    
    serializer = EventSerializer(events, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def upcoming_ongoing_events(request):
    events = Event.objects.filter(status__in=["Upcoming", "Ongoing"]).order_by('date')
    serializer = EventSerializer(events, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def bookings_by_host(request, host_id):
    """Get all bookings for events assigned to a specific host"""
    try:
        # Get all events assigned to this host
        host_events = Event.objects.filter(assigned_host=host_id)
        event_ids = host_events.values_list('id', flat=True)
        
        # Get all bookings for these events
        bookings = Booking.objects.filter(event__in=event_ids).order_by('-created_at')
        
        # Serialize the bookings
        serializer = BookingSerializer(bookings, many=True, context={'request': request})
        return Response(serializer.data)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

HITPAY_API_URL = "https://api.sandbox.hit-pay.com/v1/payment-requests"
HITPAY_API_KEY = "test_06b2632b5b7852da8076f1a08a15375ad1651972fe9d457be3d5f45a8cde2418"

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def hitpay_transactions(request):
    host_id = request.query_params.get('host_id')
    page = int(request.query_params.get('page', 1))
    per_page = int(request.query_params.get('per_page', 20))

    # First try to get from Payment table
    payments = Payment.objects.all()
    if host_id:
        payments = payments.filter(host_id=host_id)
    
    payment_count = payments.count()
    
    # If no payments found, fall back to Booking table
    if payment_count == 0:
        bookings = Booking.objects.all()
        if host_id:
            bookings = bookings.filter(host_id=host_id)
        
        total = bookings.count()
        start = (page - 1) * per_page
        end = start + per_page
        bookings_page = bookings.order_by('-created_at')[start:end]
        
        # Convert bookings to transaction format
        data = []
        for booking in bookings_page:
            data.append({
                "id": str(booking.id),
                "reference_number": booking.sno,  # Use SNO as reference
                "amount": float(booking.total_amount or booking.payment_amount or 0),
                "currency": booking.payment_currency or "SGD",
                "status": booking.payment_status or "pending",
                "email": booking.email,
                "name": booking.user_name,
                "purpose": f"Event: {booking.event_title or booking.event.title}",
                "host_id": str(booking.host_id) if booking.host_id else None,
                "host_name": booking.host.name if booking.host else None,
                "created_at": booking.created_at.isoformat() if booking.created_at else "",
                "updated_at": booking.updated_at.isoformat() if booking.updated_at else "",
                "payment_method": booking.payment_method or "paynow",
            })
    else:
        # Use Payment table data
        total = payment_count
        start = (page - 1) * per_page
        end = start + per_page
        payments_page = payments.order_by('-created_at')[start:end]
        
        data = []
        for payment in payments_page:
            data.append({
                "id": str(payment.id),
                "reference_number": payment.reference_number,
                "amount": float(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "email": payment.email,
                "name": payment.name,
                "purpose": payment.purpose,
                "host_id": str(payment.host_id) if payment.host_id else None,
                "host_name": payment.host.name if payment.host else None,
                "created_at": payment.created_at.isoformat() if payment.created_at else "",
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else "",
            })

    return Response({
        "payment_requests": data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "from": start + 1 if total > 0 else 0,
        "to": min(end, total),
    })