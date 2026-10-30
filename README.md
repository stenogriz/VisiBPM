# VisiBPM
Business process modelling tool with simplified notation.
<p align="center">
<img width="400" height="127" alt="logo" src="https://github.com/user-attachments/assets/3fb677ed-357e-40b6-ab86-326d4d80ee05" />
</p>

## About
Give businesses a simple tool to describe their processes in simple notation without the complexity of the BPMN.
Only 3 primitives to arrange:
- Process
- Document
- Outer process link

And only one major rule (enforced in the diagram): **Processes interact only via documents.**

Which, in terms of business logic, means only one thing: you need information to flow between processes. If you ask, “What about physical objects, like goods, items, shipments, etc.?” the answer is simple — you always have an accompanying document for each physical object (an invoice, order, or other form). 

Each process is relatevely easy to describe. Just answer (mainly to yourself) - *who* interacts with the input information, *when* the results should be available and *what* is an essence of the action that results in some output information.

<p align="center">
<img width="870" height="417" alt="screenshot" src="https://github.com/user-attachments/assets/51ae358e-f3a0-4e8a-bb78-bc036e81ab2b" />
</p>

## Technical
Program is just one python script which requires only PySide6 to run. If you need a binary for the unprepared environment, just use the pyinstaller.
