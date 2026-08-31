"""Marca `scripts` como paquete importable.

Existe para que una herramienta pueda reutilizar a otra sin duplicar tablas. La
re-derivacion de metadatos usa las mismas tablas de circuitos, tipos de sesion y
ajustes que el capturador: si las copiara, una correccion en una quedaria sin
aplicar en la otra, que es justo el error que la re-derivacion viene a reparar.
"""
