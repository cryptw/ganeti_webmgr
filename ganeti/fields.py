from datetime import datetime
from decimal import Decimal
import time

from django.core.exceptions import ValidationError
from django.db.models.fields import DecimalField
from django.db import models

class PreciseDateTimeField(DecimalField):
    """
    Custom model field for dealing with timestamps requiring precision greater
    than seconds.  MySQL and other databases follow the SQL92 standard:
    
        TIMESTAMP - contains the datetime field's YEAR, MONTH, DAY, HOUR,
                    MINUTE, and SECOND.

    To support greater precisions this class will convert to and from a decimal
    field.  There are issues dealing with this due to timezones, different
    epochs, etc., but the alternative is using a string field to store the
    values.
    
    By default this field will support 6 decimal places (microsceonds), but it
    can be adjusted by adding the decimal_places kwarg.
    
    By default this field will support up decimal_places+12 total digits.  This
    can be adjusted by including the max_digits kwarg.  max_digits must include
    the total of both second and microsecond digits.
    """
    
    __metaclass__ = models.SubfieldBase
    
    def __init__(self, **kwargs):
        # XXX set default values.  doing this here rather than as kwargs
        # because default ordering of DecimalField.__init__ may be different
        if not 'decimal_places' in kwargs:
            kwargs['decimal_places'] = 6
        if not 'max_digits' in kwargs:
            kwargs['max_digits'] = kwargs['decimal_places'] + 12
        
        self.shifter = 10.0**kwargs['decimal_places']
        
        super(PreciseDateTimeField, self).__init__(**kwargs)

    def to_python(self, value):
        """
        convert decimal value to a datetime
        """
        if not value:
            return None
        if isinstance(value, (datetime,)):
            return value
        if isinstance(value, (Decimal, str, unicode)):
            value = float(value)
        if isinstance(value, (float,)):
            return datetime.fromtimestamp(value)
        
        raise ValidationError('Unable to convert %s to datetime.' % value)

    def get_db_prep_value(self, value, **kwargs):
        if value:
            return time.mktime(value.timetuple()) + value.microsecond/(10**self.decimal_places)
        return None
    
    def get_db_prep_save(self, value, connection):
        if value:
            if isinstance(value, (datetime,)):
                return Decimal('%f' % (time.mktime(value.timetuple()) + value.microsecond/self.shifter))
            
            if isinstance(value, (float,)):
                return Decimal(float)
            
            if isinstance(value, (Decimal,)):
                return value
            
        return None
    
    def db_type(self, connection):
        engine = connection.settings_dict['ENGINE']

        if engine == 'django.db.backends.mysql':
            return 'decimal(%s, %s)' % (self.max_digits, self.decimal_places)
        elif engine in ('django.db.backends.postgresql', 'django.db.backends.postgresql_psycopg2'):
            return 'numeric(%s, %s)' % (self.max_digits, self.decimal_places)
        elif  engine == 'django.db.backends.sqlite3':
            return 'character'
