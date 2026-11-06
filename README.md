# VisiBPM
Business process modelling tool with simplified notation.
<p align="center">
<img width="400" height="127" alt="logo" src="https://github.com/user-attachments/assets/3fb677ed-357e-40b6-ab86-326d4d80ee05" />
</p>

## About
This tool gives businesses a simple way to describe their processes without the complexity of BPMN. The notation has only three primitives:
- Process
- Document
- External process link

It enforces one core rule in the diagram: **processes interact only through documents.**

In business terms, this means information must flow between processes. Physical objects such as goods, items, and shipments are covered by the same rule, because each one is always accompanied by a document (an invoice, an order, or another form) that carries its information.

Process description takes three answers:
- **Who** works with the input information?
- **When** do the results need to be available?
- **What** is the essential action that produces the output?

<br />
<p align="center">
<img width="931" height="500" alt="Clipboard_11-06-2026_01" src="https://github.com/user-attachments/assets/2007c319-74de-4f85-8d4d-d30e68d38536" />
</p>

## Technical
The application is a single Python script with one dependency, PySide6. To distribute it as a standalone binary for environments without Python, build it with PyInstaller.
