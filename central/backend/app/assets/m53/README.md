# M53 rendering assets

`source_format.json` holds fixed labels/clauses, named variables, and the procedural
confirmation requirements. It was reconstructed from the user's scanned compilation,
PDF pages 18–20. Historical people, dates, case facts, signatures, and teaching annotations
are not template defaults. This reconstruction is not an institution-issued master form.

The canonical PDF uses the bundled Noto Naskh Arabic Regular and Bold fonts, licensed
under the SIL Open Font License in `OFL.txt`. Sources:

- https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoNaskhArabic
- https://github.com/notofonts/noto-fonts/blob/main/LICENSE

Latin characters and punctuation use the Bitstream Vera fonts shipped with ReportLab.
Both fonts are embedded in the generated PDF. Editable Word files embed the Noto Arabic
fonts and use Arial for Latin text. The archived PDF is the print master.

`report_m53.REVISION` identifies the renderer revision. The archived context contains the
exact clause definition, layout, reviewed values, authenticated confirmations and format
digest. Change the revision when changing the form in a future release.
