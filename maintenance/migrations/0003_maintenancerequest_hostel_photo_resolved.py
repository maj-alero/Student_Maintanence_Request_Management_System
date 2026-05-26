from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('maintenance', '0002_alter_maintenancerequest_affected_users_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='maintenancerequest',
            name='hostel_name',
            field=models.CharField(
                choices=[
                    ('Lydia Hall', 'Lydia Hall'), ('Deborah Hall', 'Deborah Hall'),
                    ('Mary Hall', 'Mary Hall'), ('Dorcas Hall', 'Dorcas Hall'),
                    ('Daniel Hall', 'Daniel Hall'), ('Joseph Hall', 'Joseph Hall'),
                    ('Paul Hall', 'Paul Hall'), ('Peter Hall', 'Peter Hall'),
                    ('John Hall', 'John Hall'), ('Joshua Hall', 'Joshua Hall'),
                ],
                default='',
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name='maintenancerequest',
            name='wing',
            field=models.CharField(
                choices=[('A', 'Wing A'), ('B', 'Wing B'), ('C', 'Wing C'),
                         ('D', 'Wing D'), ('E', 'Wing E'), ('F', 'Wing F'),
                         ('G', 'Wing G'), ('H', 'Wing H')],
                default='A',
                max_length=1,
            ),
        ),
        migrations.AddField(
            model_name='maintenancerequest',
            name='room_number',
            field=models.CharField(default='', max_length=10),
        ),
        migrations.AddField(
            model_name='maintenancerequest',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to='request_photos/'),
        ),
        migrations.AddField(
            model_name='maintenancerequest',
            name='resolved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
