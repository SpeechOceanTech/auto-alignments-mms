"""Private JSON-lines worker: load a local fastText model once on the CPU.

The model is supplied explicitly by the operator. No input or errors are logged.
"""
import json
import sys


def main():
    import fasttext

    model = fasttext.load_model(sys.argv[1])
    labels = [label.removeprefix('__label__') for label in model.get_labels()]
    for line in sys.stdin:
        try:
            pieces = json.loads(line)['pieces']
            predictions = []
            for piece in pieces:
                names, scores = model.predict(piece.replace('\n', ' '), k=1)
                predictions.append([names[0].removeprefix('__label__'), float(scores[0])])
            response = {'labels': labels, 'predictions': predictions}
        except Exception:
            response = {'error': 'prediction_failed'}
        sys.stdout.write(json.dumps(response, ensure_ascii=True) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
