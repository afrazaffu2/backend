from django.db import migrations, models
import uuid

def generate_default_slug(apps, schema_editor):
    Event = apps.get_model('events', 'Event')
    for event in Event.objects.all():
        event.slug = f"default-{uuid.uuid4()}"
        event.save()

class Migration(migrations.Migration):

    dependencies = [
        ('events', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='slug',
            field=models.SlugField(unique=True, null=True),  # TEMPORARY nullable
        ),
        migrations.RunPython(generate_default_slug),
        migrations.AlterField(
            model_name='event',
            name='slug',
            field=models.SlugField(unique=True),  # remove null after assigning
        ),
    ]
