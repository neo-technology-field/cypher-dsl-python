Architecture decisions
======================

Each record states one decision that is expensive to reverse or that a reasonable
contributor would challenge. Records are accepted, superseded or rejected by writing a new
record, so a superseded decision stays readable and its links keep working.

.. toctree::
   :maxdepth: 1

   0001-record-architecture-decisions
   0002-port-vocabulary-not-java-api
   0003-separate-dialect-language-and-server-target
   0004-reuse-syntax-through-visitors
   0005-inline-literals-and-explicit-parameters
   0006-keep-runtime-independent-of-drivers
   0007-support-upstream-maintained-python
   0008-use-uv-build-with-nox

New records copy ``template.md`` and take the next number. The template is not itself a
record, so it is not listed above.
