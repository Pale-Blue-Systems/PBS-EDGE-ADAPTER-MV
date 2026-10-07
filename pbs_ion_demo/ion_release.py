"""
The ION release the demonstration is built and verified against.

scripts/build_ion.sh reads the same values from scripts/ion-release.env;
TESTS/test_ion_demo_units.py checks that the two agree.
"""

ION_REPOSITORY = "https://github.com/nasa-jpl/ION-DTN.git"
ION_RELEASE_TAG = "ion-open-source-4.2.0"
ION_RELEASE_COMMIT = "568df887cb9f18aa8ec013b1a566d83215e499ae"
ION_VERSION_STRING = "ION-OPEN-SOURCE-4.2.0"
