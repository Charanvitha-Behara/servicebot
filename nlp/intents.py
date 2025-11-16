subjects = {
    "dbms": ["dbms", "database"],
    "data structures": ["ds", "data", "structures"]
}

def detect_subject(tokens):
    for subject, keywords in subjects.items():
        for word in tokens:
            if word in keywords:
                return subject
    return None
