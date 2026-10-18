#!/bin/bash
# Lanzador del músico. El verificador y la cátedra lo llaman así:
#
#   ./correr.sh <nombre> <tipo> <teatro host:puerto> <instrumento host:puerto>
#
# Tiene que compilar si hace falta, levantar todos los procesos del músico y
# quedarse hasta que el teatro mande FIN. Al terminar no puede quedar ningún
# proceso vivo.
echo "correr.sh: todavía no hay músico. Me llamaron con: $*" >&2
exit 1
