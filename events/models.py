from django.db import models
from hosts.models import Host
from django.contrib.postgres.fields import JSONField
from django.utils.text import slugify
from django.utils import timezone
import os
import uuid
from datetime import datetime
import qrcode
from io import BytesIO
from django.core.files import File
from PIL import Image as PILImage
from django.db import transaction
from django.core.exceptions import ValidationError
from django.conf import settings

def event_image_path(instance, filename):
    """Generate unique file path for event images"""
    # Get file extension
    ext = os.path.splitext(filename)[1]
    
    # Generate unique filename with timestamp and UUID
    unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    
    # Try to get event slug, fallback to event ID or temp
    if hasattr(instance, 'event') and instance.event:
        if instance.event.slug:
            event_identifier = instance.event.slug
        elif instance.event.id:
            event_identifier = f"event_{instance.event.id}"
        else:
            event_identifier = "temp"
    else:
        event_identifier = "temp"
    
    return f'events/{event_identifier}/{instance.image_type}/{unique_filename}'

def booking_qr_path(instance, filename):
    """Generate file path for booking QR codes"""
    return f'bookings/{instance.event.slug}/{filename}'

class EventImage(models.Model):
    IMAGE_TYPES = [
        ('cover', 'Cover Image'),
        ('thumbnail', 'Thumbnail Image'),
        ('square', 'Square Image'),
    ]
    
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='event_images')
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPES)
    image = models.ImageField(upload_to=event_image_path)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['event', 'image_type']
    
    def __str__(self):
        return f"{self.event.title} - {self.image_type}"

class Event(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=255)
    type = models.CharField(max_length=50)
    status = models.CharField(max_length=50)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    assigned_host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name='events')
    is_published = models.BooleanField(default=False)  # type: ignore
    category = models.CharField(max_length=50)
    tags = models.JSONField(default=list, blank=True)
    amenities = models.JSONField(default=list, blank=True)
    images = models.JSONField(default=dict, blank=True)  # Keep for backward compatibility
    packages = models.JSONField(default=list, blank=True)
    additional_members_config = models.JSONField(default=dict, blank=True)
    food_preference_config = models.JSONField(default=dict, blank=True)
    faq = models.JSONField(default=list, blank=True)
    terms_and_conditions = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug or self.slug == "":
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Event.objects.filter(slug=slug).exists():  # type: ignore[attr-defined]
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)
    
    @property
    def image_urls(self):
        """Get image URLs for the event"""
        urls = {}
        for image in self.event_images.all():
            urls[image.image_type] = image.image.url
        return urls

class EmergencyContact(models.Model):
    """Emergency contact information for bookings"""
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    relationship = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.relationship})"

class Booking(models.Model):
    # Event Information
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='bookings')
    host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name='bookings', null=True, blank=True)
    event_title = models.CharField(max_length=255, blank=True)  # Store event title at time of booking
    event_date = models.DateTimeField(null=True, blank=True)  # Store event date at time of booking
    event_location = models.CharField(max_length=255, blank=True)  # Store event location at time of booking
    
    # Primary Contact Information
    sno = models.CharField(max_length=20, unique=True)  # Serial Number
    user_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    
    # Registration Details
    member_count = models.IntegerField(default=1)
    selected_package = models.JSONField(default=dict, blank=True)  # Store package details
    food_preference = models.CharField(max_length=100, blank=True)
    additional_members = models.JSONField(default=list, blank=True)  # Store additional member details
    
    # Emergency Contact
    emergency_contact = models.ForeignKey(EmergencyContact, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Special Requirements
    special_requirements = models.TextField(blank=True)
    
    # QR Code and Status
    qr_code = models.ImageField(upload_to=booking_qr_path, blank=True, null=True)
    is_activated = models.BooleanField(default=False)  # Simple boolean status
    
    # Payment Information
    payment_method = models.CharField(max_length=50, choices=[
        ('card', 'Credit/Debit Card'),
        ('paynow', 'PayNow'),
        ('bank_transfer', 'Bank Transfer'),
        ('grabpay', 'GrabPay'),
        ('favepay', 'FavePay'),
    ], default='paynow')
    payment_reference = models.CharField(max_length=100, blank=True)
    payment_status = models.CharField(max_length=50, choices=[
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='pending')
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    payment_currency = models.CharField(max_length=10, default='SGD')
    
    # Terms and Conditions
    terms_accepted = models.BooleanField(default=False)
    privacy_policy_accepted = models.BooleanField(default=False)
    
    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    source = models.CharField(max_length=50, default='web')
    
    # Legacy fields for backward compatibility
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.sno} - {self.user_name}"

    def save(self, *args, **kwargs):
        # Generate SNO if not provided
        if not self.sno:
            self.sno = self.generate_unique_sno()
        
        # Generate QR code if not exists
        if not self.qr_code:
            self.generate_qr_code()
        
        # Set legacy total_amount for backward compatibility
        if self.payment_amount > 0:
            self.total_amount = self.payment_amount
        
        super().save(*args, **kwargs)

    @transaction.atomic
    def generate_unique_sno(self):
        """Generate a unique SNO with proper locking to prevent duplicates"""
        # Get event acronym
        event_acronym = ''.join([word[0].upper() for word in self.event.title.split()[:3]])
        
        # Find the highest existing booking number for this event
        existing_bookings = Booking.objects.filter(event=self.event).order_by('-sno')
        
        if existing_bookings.exists():
            # Extract the highest number from existing SNOs
            highest_sno = existing_bookings.first().sno
            try:
                # Try to extract number from format like "ABC-001"
                highest_number = int(highest_sno.split('-')[-1])
            except (ValueError, IndexError):
                # If parsing fails, count existing bookings
                highest_number = existing_bookings.count()
        else:
            highest_number = 0
        
        # Generate new SNO with incremented number
        new_number = highest_number + 1
        new_sno = f"{event_acronym}-{new_number:03d}"
        
        # Double-check uniqueness (in case of race conditions)
        counter = 1
        while Booking.objects.filter(sno=new_sno).exists():
            new_sno = f"{event_acronym}-{(new_number + counter):03d}"
            counter += 1
        
        return new_sno

    def generate_qr_code(self):
        """Generate QR code for the booking"""
        # Use frontend URL for activation (mobile accessible)
        frontend_url = getattr(settings, 'FRONTEND_URL', 'https://event-management-fe.onrender.com')
        activation_url = f"{frontend_url}/activate/{self.sno}"
        qr_data = activation_url
        
        # Create QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to Django File
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        # Save to model
        filename = f"{self.sno}_qr.png"
        self.qr_code.save(filename, File(buffer), save=False)

    @property
    def qr_code_url(self):
        """Get QR code URL"""
        if self.qr_code:
            return self.qr_code.url
        return None

    @property
    def status(self):
        """Get status string for backward compatibility"""
        return "Activated" if self.is_activated else "Not Scanned"

class Payment(models.Model):
    """Enhanced Payment model for storing comprehensive payment information"""
    # Payment Identification
    reference_number = models.CharField(max_length=100, unique=True)
    payment_request_id = models.CharField(max_length=100, blank=True)
    host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    
    # Payment Details
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='SGD')
    payment_type = models.CharField(max_length=20, default='online')

    payment_methods = models.JSONField(default=list, blank=True)  # Array of payment methods
    
    # Status and Processing
    status = models.CharField(max_length=50, choices=[
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ])
    
    # Customer Information
    email = models.EmailField(blank=True)
    name = models.CharField(max_length=255, blank=True)
    purpose = models.CharField(max_length=255, blank=True)
    
    # Related Booking (if applicable)
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    
    # Timestamps
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    
    # Additional Payment Data
    payment_data = models.JSONField(default=dict, blank=True)  # Store additional payment gateway data
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference_number} - {self.status} - {self.amount} {self.currency}"

class RegistrationPayment(models.Model):
    """Model to track registration-specific payment information"""
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='registration_payment')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='registration_payments')
    
    # Payment processing details
    gateway_response = models.JSONField(default=dict, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    gateway_fees = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment for {self.booking.sno}"

class AdditionalMember(models.Model):
    """Model for storing additional member information"""
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='additional_member_details')
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    food_preference = models.CharField(max_length=100, blank=True)
    special_requirements = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.name} - {self.booking.sno}"
