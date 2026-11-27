# C/C++ CWE candidate index

- CWE-125: A reachable read accesses data outside an object's or buffer's actual bounds because an index, offset, or read length is not effectively constrained.
- CWE-476: A feasible null pointer reaches an explicit or implicit dereference, including a data-access call requiring a valid pointer, without an effective guard.
- CWE-401: Dynamically allocated memory remains unreleased when its effective lifetime ends or its last owning reference is lost, with no ownership transfer or automatic cleanup on that path.
- CWE-606: An externally supplied, configurable, hardware-derived, or otherwise exposed input controls a loop condition without effective validation of its execution bounds or termination; a function parameter alone does not establish input provenance.
- CWE-197: An explicit or implicit conversion to a narrower numeric representation loses significant bits or magnitude for a feasible source value, without an effective range check or documented intentional narrowing.
- CWE-362: Two accesses to the same or overlapping shared memory may execute concurrently, at least one writes and at least one is non-atomic, without effective common synchronization or ordering.
- CWE-190: Reachable integer arithmetic has a mathematical result above the actual operation type's representable maximum after promotions and conversions, without effective overflow prevention or safe handling.
- CWE-191: Reachable integer arithmetic has a mathematical result below the actual operation type's representable minimum after promotions and conversions, including unsigned underflow wraparound, without effective prevention or safe handling.
