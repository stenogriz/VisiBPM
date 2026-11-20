# VisiBPM
Business process modelling tool with simplified notation.
<p align="center">
<img width="400" height="127" alt="logo" src="https://github.com/user-attachments/assets/3fb677ed-357e-40b6-ab86-326d4d80ee05" />
</p>

## About
This tool gives businesses a simple way to describe their processes without the complexity of BPMN. The notation has only three primitives:
- Process
- Document
- External process link (a process outside the scope of the current procedure)

<br />
<p align="center">
  <img width="892" height="183" alt="sample procedure" src="https://github.com/user-attachments/assets/97136a2d-570d-4523-a500-8b488ea133db" />
</p>

It enforces one core rule in the procedure diagram: **processes interact only through documents.**

In business terms, this means information must flow between processes. Physical objects such as goods, items, and shipments are covered by the same rule, because each one is always accompanied by a document (an invoice, an order, or another form) that carries its information.

Process description takes three answers:
- **Who** works with the input information?
- **When** do the results need to be available?
- **What** is the essential action that produces the output?

<br />
<p align="center">
<img width="1379" height="704" alt="screenshot" src="https://github.com/user-attachments/assets/e1f83a2b-7ecf-4308-b8f2-dd27dea0f69b" />
</p>

## Technical
The application is a single Python script with one dependency, PySide6. To distribute it as a standalone binary for environments without Python, build it with PyInstaller.
