# Run all tests
cd $PSScriptRoot\backend
python test_gst_engine.py; if ($?) { python test_ocr_postproc.py }; if ($?) { python test_validation_layer.py }; if ($?) { python test_xml_generator.py }
