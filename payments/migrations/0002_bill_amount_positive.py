from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payments', '0001_initial')]

    operations = [
        migrations.AddConstraint(
            model_name='bill',
            constraint=models.CheckConstraint(
                condition=models.Q(amount__gt=0), name='bill_amount_positive'
            ),
        ),
    ]
