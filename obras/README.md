# Obras

El teatro lee obras en este formato:

```
OBRA nombre
TEMPO 120
PARTE flauta
NOTA <beat> <duración> <pitch MIDI> <dinámica 0-100>
...
PARTE violin
...
```

Una parte por instrumento, con las notas ordenadas por beat. Las notas que
empiezan en el mismo beat suenan juntas: en la guitarra y en el piano son
acordes, y en las cuerdas frotadas, dobles cuerdas. Todas se pueden digitar
con las tablas de `tablas/`.

- `escala.txt`: doce notas de cada tabla, para probar.
- `fray_santiago.txt`: canon a dos voces, 40 beats. La que usa el verificador.
- `bossa_del_relojero.txt`: guitarra sola, bajo y acordes de tres cuerdas. La
  usa el nivel 3 del verificador.
- `muestrario.txt`: cada instrumento toca solo dos compases, y al final tocan
  todos juntos.
- `himno_alegria.txt`, `para_elisa.txt`: Beethoven.
- `canon_pachelbel.txt`: Pachelbel, bajo y tres voces en canon.
- `minueto_en_sol.txt`: Petzold, del Cuaderno de Ana Magdalena Bach.
- `preludio_cello.txt`, `jesu_alegria.txt`: Bach.
- `greensleeves.txt`: tradicional inglesa.
- `pequena_serenata.txt`, `rondo_alla_turca.txt`: Mozart.
- `gymnopedie.txt`: Satie.
- `cuando_los_santos.txt`: tradicional de Nueva Orleans.
- `primavera.txt`: Vivaldi, el comienzo del primer movimiento.
- `cancion_de_cuna.txt`: Brahms.
- `carmen_preludio.txt`: Bizet, el comienzo del preludio.

Todas son de dominio público, salvo `primavera.txt` (CC BY-SA 3.0) y
`carmen_preludio.txt` (CC BY-SA 2.5), que salen de MIDI tipeados por el
Mutopia Project (https://www.mutopiaproject.org, piezas 301 y 635) y quedan
bajo la misma licencia.
