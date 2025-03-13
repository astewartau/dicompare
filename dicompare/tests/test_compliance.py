
import dicompare

def test_compliance():
    session = dicompare.load_dicom_session("/home/ashley/downloads/michael-green/GREForQSM/", show_progress=False)
    session = dicompare.assign_acquisition_and_run_numbers(session)
    reference_fields, ref_session = dicompare.load_json_session(json_ref='/home/ashley/downloads/michael-green/ref.json')
    session_map = { "acq-kegrene51015202508-1": "acq-kegrene51015202508-1", "acq-kegrene51015202508-2": "acq-kegrene51015202508-2" }
    compliance_summary = dicompare.check_session_compliance_with_json_reference(in_session=session, ref_session=ref_session, session_map=session_map)

test_compliance()

