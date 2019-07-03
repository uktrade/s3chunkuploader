from django.db.models import FileField


class S3FileField(FileField):
    """
    A replacement FileField, satisfied with the file path to S3
    """
    def save(self, name, content, save=True):
        name = self.field.generate_filename(self.instance, name)
        self.name = name
        setattr(self.instance, self.field.name, self.name)
        self._committed = True
        # Save the object because it has changed, unless save is False
        if save:
            self.instance.save()
    save.alters_data = True
