from templates.response_templates import get_all_templates

def test_template_fill():
    templates = get_all_templates()
    hospital_covered = templates.get("hospital_covered")
    print(f"Template: {hospital_covered}")
    
    # Try to format it
    try:
        formatted = hospital_covered.format(
            coverage_pct="90%",
            hospital_name="Beacon Hospital",
            max_limit="€5,000"
        )
        print(f"Formatted: {formatted}")
        assert "Beacon Hospital" in formatted
        print("Template verification SUCCESS!")
    except Exception as e:
        print(f"Template verification FAILED: {e}")
        exit(1)

if __name__ == "__main__":
    test_template_fill()
