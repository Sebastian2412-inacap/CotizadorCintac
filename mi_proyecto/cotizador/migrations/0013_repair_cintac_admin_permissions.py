from django.db import migrations


GROUP_NAME = "Administración CINTAC"
PERMISSIONS = {
    "auth": {"user": ("add", "change", "delete", "view")},
    "cotizador": {
        "quotehistory": ("delete", "view"),
        "freightrate": ("add", "change", "delete", "view"),
        "route": ("add", "change", "delete", "view"),
    },
}


def repair_cintac_admin_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    database = schema_editor.connection.alias
    group, _ = Group.objects.using(database).get_or_create(name=GROUP_NAME)
    permission_ids = []

    for app_label, models in PERMISSIONS.items():
        for model, actions in models.items():
            content_type, _ = ContentType.objects.using(database).get_or_create(
                app_label=app_label,
                model=model,
            )
            for action in actions:
                codename = f"{action}_{model}"
                permission, _ = Permission.objects.using(database).get_or_create(
                    content_type=content_type,
                    codename=codename,
                    defaults={"name": f"Can {action} {model}"},
                )
                permission_ids.append(permission.pk)

    group.permissions.set(permission_ids)


class Migration(migrations.Migration):
    dependencies = [
        ("cotizador", "0012_cintac_admin_group"),
    ]

    operations = [
        migrations.RunPython(
            repair_cintac_admin_permissions,
            migrations.RunPython.noop,
        ),
    ]
