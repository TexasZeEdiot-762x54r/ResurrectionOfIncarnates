import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client/tools'))
import library_pages


class LibraryPresentationTests(unittest.TestCase):
    def test_story_heading_uses_capture_supported_uppercase_display(self):
        page = library_pages.render(
            'en',
            'story',
            {'item': ['the-era-of-incarnates']},
            library_pages.catalogue(),
            library_pages.transcript(),
        ).decode('utf-8')
        css = (library_pages.ROOT / 'library.css').read_text(encoding='utf-8')

        self.assertIn('<h1 class="story-title">The Era of Incarnates</h1>', page)
        self.assertIn('.story-title { text-transform: uppercase;', css)
        self.assertIn('It is as if Nature itself is in revolt.', page)
        self.assertNotIn('story-the-era-of-incarnates.jpg', page.split('<article class="prose">', 1)[1])


if __name__ == '__main__':
    unittest.main()
